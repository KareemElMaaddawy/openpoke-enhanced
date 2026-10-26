"""OpenRouterClient against a mocked HTTP transport (no network): retries, errors, usage, raw logs, cap."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from evals.agent_overload.harness import llm

OK_BODY = {
    "id": "gen-1",
    "model": "openai/gpt-6-luna-20260922",
    "provider": "OpenAI",
    "system_fingerprint": "fp_1",
    "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "cost": 0.000125,
        "completion_tokens_details": {"reasoning_tokens": 20},
        "prompt_tokens_details": {"cached_tokens": 0},
    },
}


def client_with(responses, raw_dir=None, cap=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    client = llm.OpenRouterClient(confirm_spend=True, api_key="test-key", raw_dir=raw_dir, spend=llm.SpendTracker(cap))
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, calls


async def no_sleep(_seconds):
    return None


def chat(client):
    async def go():
        try:
            return await client.chat(purpose="routing", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "x"}], system="s", seed=7)
        finally:
            await client.aclose()

    return asyncio.run(go())


@mock.patch.object(llm.asyncio, "sleep", no_sleep)
class OpenRouterClientTest(unittest.TestCase):
    def test_success_captures_usage_and_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, calls = client_with([(200, OK_BODY)], raw_dir=Path(tmp))
            data, record = chat(client)
            self.assertEqual(data["id"], "gen-1")
            self.assertEqual((record.prompt_tokens, record.completion_tokens, record.reasoning_tokens), (1000, 50, 20))
            self.assertEqual(record.cost, 0.000125)
            self.assertFalse(record.cost_estimated)
            self.assertEqual(record.provider, "OpenAI")
            self.assertEqual(record.returned_model, "openai/gpt-6-luna-20260922")
            self.assertEqual(record.attempts, 1)
            self.assertEqual(calls[0]["seed"], 7)
            self.assertEqual(calls[0]["usage"], {"include": True})
            raw = json.loads((Path(tmp) / record.raw_path).read_text())
            self.assertNotIn("test-key", json.dumps(raw))
            self.assertEqual(client.spend.total_usd, 0.000125)

    def test_retries_429_and_5xx_then_succeeds(self):
        client, calls = client_with([(429, {"error": "rate"}), (502, "bad gateway"), (200, OK_BODY)])
        _data, record = chat(client)
        self.assertEqual(record.attempts, 3)
        self.assertEqual(len(calls), 3)

    def test_network_errors_are_retried_until_exhausted(self):
        client, calls = client_with([httpx.ConnectError("down")])
        with self.assertRaises(llm.ApiError):
            chat(client)
        self.assertEqual(len(calls), 6)  # 1 + 5 retries

    def test_400_is_not_retried(self):
        client, calls = client_with([(400, {"error": {"message": "bad param"}})])
        with self.assertRaises(llm.ApiError):
            chat(client)
        self.assertEqual(len(calls), 1)

    def test_error_object_in_200_body(self):
        client, calls = client_with([(200, {"error": {"code": 502, "message": "upstream"}}), (200, OK_BODY)])
        _data, record = chat(client)
        self.assertEqual(record.attempts, 2)
        client, calls = client_with([(200, {"error": {"code": 400, "message": "invalid"}})])
        with self.assertRaises(llm.ApiError):
            chat(client)
        self.assertEqual(len(calls), 1)

    def test_missing_cost_is_estimated_and_flagged(self):
        body = json.loads(json.dumps(OK_BODY))
        del body["usage"]["cost"]
        client, _ = client_with([(200, body)])
        _data, record = chat(client)
        self.assertTrue(record.cost_estimated)
        self.assertAlmostEqual(record.cost, (1000 * 0.10 + 50 * 0.50) / 1e6)

    def test_cap_blocks_the_next_call(self):
        client, calls = client_with([(200, OK_BODY)], cap=0.0001)

        async def go():
            await client.chat(purpose="routing", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "x"}])
            await client.chat(purpose="routing", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "x"}])

        with self.assertRaises(llm.SpendCapReached):
            asyncio.run(go())
        self.assertEqual(len(calls), 1)

    def test_requires_key(self):
        with self.assertRaises(llm.SpendNotConfirmed):
            llm.OpenRouterClient(confirm_spend=True, api_key="  ")


if __name__ == "__main__":
    unittest.main()
