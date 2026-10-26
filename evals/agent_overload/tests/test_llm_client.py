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


class FakeTime:
    """A clock whose sleep advances it, so pacing waits cost no real time."""

    def __init__(self):
        self.now = 1000.0
        self.slept = 0.0

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        self.slept += seconds


def client_with(responses, raw_dir=None, cap=None, rpm=None, fake_time=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    client = llm.OpenRouterClient(confirm_spend=True, api_key="test-key", raw_dir=raw_dir, spend=llm.SpendTracker(cap), rpm=rpm)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fake_time = fake_time or FakeTime()
    client._limiters["openai/gpt-6-luna"] = llm.RateLimiter(rpm, clock=fake_time.clock, sleep=fake_time.sleep)
    client.fake_time = fake_time
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

    def test_429_waits_for_the_reported_reset(self):
        fake_time = FakeTime()
        reset_ms = int((llm.time.time() + 30) * 1000)
        body = {"error": {"message": "Rate limit exceeded: new-account-rpm", "code": 429,
                          "metadata": {"headers": {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_ms)}}}}
        client, calls = client_with([(429, body), (200, OK_BODY)], fake_time=fake_time)
        _data, record = chat(client)
        self.assertEqual(record.attempts, 2)
        self.assertTrue(28 <= fake_time.slept <= 31, fake_time.slept)

    def test_pacing_spreads_calls_over_minutes(self):
        fake_time = FakeTime()
        client, calls = client_with([(200, OK_BODY)], rpm=3, fake_time=fake_time)

        async def go():
            for _ in range(7):
                await client.chat(purpose="routing", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "x"}])
            await client.aclose()

        asyncio.run(go())
        self.assertEqual(len(calls), 7)
        self.assertTrue(120 <= fake_time.slept < 121, fake_time.slept)  # 7 calls at 3/min: two full waits

    def test_requires_key(self):
        with self.assertRaises(llm.SpendNotConfirmed):
            llm.OpenRouterClient(confirm_spend=True, api_key="  ")


if __name__ == "__main__":
    unittest.main()


class RateLimitHelpersTest(unittest.TestCase):
    def test_rate_limit_wait_sources(self):
        now = 1_800_000_000.0
        r = httpx.Response(429, headers={"Retry-After": "12"}, json={})
        self.assertEqual(llm.rate_limit_wait(r, now), 12.0)
        r = httpx.Response(429, json={"error": {"metadata": {"headers": {"X-RateLimit-Reset": str(int((now + 20) * 1000))}}}})
        self.assertAlmostEqual(llm.rate_limit_wait(r, now), 20.0, places=2)
        r = httpx.Response(429, json={"error": {"metadata": {"headers": {"X-RateLimit-Reset": str(int((now + 600) * 1000))}}}})
        self.assertEqual(llm.rate_limit_wait(r, now), llm.MAX_RATE_LIMIT_WAIT_S)
        self.assertIsNone(llm.rate_limit_wait(httpx.Response(429, text="slow down"), now))
