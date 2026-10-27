"""Pinned model clients with usage capture, retries, raw logging and a spend cap.

Every model call in the experiment (routing, summarizer, token probe, fixture
generation) goes through ``ModelClient.chat`` so cost and latency are counted the
same way for every method. ``OpenRouterClient`` makes real, paid calls and refuses
to exist unless the caller confirmed spend. ``FakeClient`` answers deterministically
without any network access; tests and ``--fake-model`` runs use it.

The payload is production's (``model``, ``messages`` with the system prompt first
via ``openrouter_client.client._build_messages``, ``stream: false``, ``tools``) plus
only ``provider``, ``usage`` and ``seed`` (design: Model calls), and ``max_tokens``
for token probes.

``OpenAIClient`` sends the same calls straight to OpenAI's API (configured with
``models.api: "openai"``): the OpenRouter-only keys are dropped, the model alias is
mapped to a dated snapshot, and cost is estimated from the pricing table (cached
input at its own price), since OpenAI's usage has no cost field.
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import json
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from server.openrouter_client.client import OpenRouterBaseURL, _build_messages

from .util import EVAL_ROOT, canonical_json, sha256_hex, slug_tokens

PRICING_PATH = EVAL_ROOT / "configs" / "pricing.json"
TIMEOUT_S = 60.0
BACKOFF_S = (1, 2, 4, 8, 16)
# OpenRouter limits new accounts to 20 requests per minute per model (seen 2026-10-26),
# so paid clients pace themselves under that by default. --rpm overrides it; 0 disables pacing.
DEFAULT_RPM = 18.0
# OpenAI Tier 1 for gpt-6-luna: 500 requests and 500,000 tokens per minute (model page, 2026-10-27).
# At about 6,100 prompt tokens per call the token limit binds near 80 calls a minute.
OPENAI_DEFAULT_RPM = 75.0
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_ONLY_KEYS = ("provider", "usage")
MAX_RATE_LIMIT_WAIT_S = 65.0
ADDED_KEYS = ("provider", "usage", "seed", "max_tokens")

# The call position (case_id, N, mode, rep, turn) of the unit being run; read for seeds and records.
CALL_CONTEXT: contextvars.ContextVar[dict] = contextvars.ContextVar("agent_overload_call_context", default={})


class ApiError(RuntimeError):
    """A model call failed after all retries (the turn becomes ``api_error``)."""


class SpendCapReached(RuntimeError):
    """The run's cost cap was reached; no further calls are made."""


class SpendNotConfirmed(RuntimeError):
    """A paid client was requested without ``--confirm-spend``."""


# ---------------------------------------------------------------------------
# Pricing


def load_pricing(path: Path = PRICING_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def estimate_cost(
    model: str, input_tokens: float, output_tokens: float, pricing: Optional[dict] = None, cached_tokens: float = 0
) -> float:
    """Cost at the table's prices. ``cached_tokens`` (part of ``input_tokens``) use ``cached_input`` if listed."""
    prices = (pricing or load_pricing())["prices_per_million"]
    if model not in prices:
        raise KeyError(f"no price for {model} in {PRICING_PATH.name}")
    entry = prices[model]
    cached = min(cached_tokens or 0, input_tokens)
    cached_price = entry.get("cached_input", entry["input"])
    return ((input_tokens - cached) * entry["input"] + cached * cached_price + output_tokens * entry["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Records


@dataclass
class CallRecord:
    call_id: str
    purpose: str
    model: str
    request_sha256: str
    seed: Optional[int]
    context: dict
    response_id: Optional[str] = None
    returned_model: Optional[str] = None
    provider: Optional[str] = None
    system_fingerprint: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    cost: Optional[float] = None
    cost_estimated: bool = False
    finish_reason: Optional[str] = None
    latency_ms: Optional[float] = None
    attempts: int = 0
    raw_path: Optional[str] = None
    error: Optional[str] = None
    fake: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def build_payload(
    *,
    model: str,
    messages: list[dict],
    system: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    provider: Optional[dict] = None,
    seed: Optional[int] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Production's payload (``request_chat_completion``) plus the harness keys."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": _build_messages(copy.deepcopy(messages), system),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if provider:
        payload["provider"] = provider
    payload["usage"] = {"include": True}
    if seed is not None:
        payload["seed"] = seed
    for key, value in (extra or {}).items():
        payload[key] = value
    return payload


def production_view(payload: dict) -> dict:
    """The payload without the keys the harness adds (for the parity test)."""
    return {k: v for k, v in payload.items() if k not in ADDED_KEYS}


def _usage_fields(data: dict) -> dict:
    usage = data.get("usage") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": completion_details.get("reasoning_tokens"),
        "cached_tokens": prompt_details.get("cached_tokens"),
        "cost": usage.get("cost"),
    }


# ---------------------------------------------------------------------------
# Spend tracking


class SpendTracker:
    """Running total for one run or fixture step, with an optional cap."""

    def __init__(self, cap_usd: Optional[float] = None):
        self.cap_usd = cap_usd
        self.total_usd = 0.0
        self.calls = 0
        self.capped = False
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self.cap_usd is not None and self.total_usd >= self.cap_usd:
                self.capped = True
                raise SpendCapReached(f"spend cap ${self.cap_usd:.2f} reached (${self.total_usd:.4f})")

    def charge(self, cost: Optional[float]) -> None:
        with self._lock:
            self.calls += 1
            self.total_usd += float(cost or 0.0)


# ---------------------------------------------------------------------------
# Request pacing


class RateLimiter:
    """At most ``rpm`` request starts in any rolling 60 seconds, plus a pause after a 429.

    One limiter per model, since OpenRouter's limit is per model. Every HTTP attempt,
    retries included, counts against the limit.
    """

    def __init__(self, rpm: Optional[float], clock: Callable[[], float] = time.monotonic, sleep=None):
        self.rpm = rpm if rpm and rpm > 0 else None
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._starts: deque = deque()
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    def pause(self, seconds: float) -> None:
        self._paused_until = max(self._paused_until, self._clock() + seconds)

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                if now < self._paused_until:
                    await self._sleep(self._paused_until - now)
                    continue
                if self.rpm is None:
                    return
                while self._starts and now - self._starts[0] >= 60.0:
                    self._starts.popleft()
                if len(self._starts) < self.rpm:
                    self._starts.append(now)
                    return
                await self._sleep(60.0 - (now - self._starts[0]) + 0.05)


def rate_limit_wait(response: "httpx.Response", now_epoch: Optional[float] = None) -> Optional[float]:
    """Seconds until a 429's limit resets, from Retry-After or X-RateLimit-Reset (header or error metadata)."""
    now_epoch = time.time() if now_epoch is None else now_epoch
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(MAX_RATE_LIMIT_WAIT_S, max(1.0, float(retry_after)))
        except ValueError:
            pass
    reset = response.headers.get("x-ratelimit-reset")
    if not reset:
        try:
            body = response.json()
            reset = ((body.get("error") or {}).get("metadata") or {}).get("headers", {}).get("X-RateLimit-Reset")
        except (ValueError, AttributeError):
            reset = None
    if reset:
        try:
            value = float(reset)
        except ValueError:
            return None
        seconds = value / 1000.0 - now_epoch if value > 1e11 else value - now_epoch
        return min(MAX_RATE_LIMIT_WAIT_S, max(1.0, seconds))
    # OpenAI: durations such as "6s", "1m30s" or "250ms" until each limit resets.
    durations = [parse_duration(response.headers.get(h)) for h in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens")]
    durations = [d for d in durations if d is not None]
    if durations:
        return min(MAX_RATE_LIMIT_WAIT_S, max(1.0, max(durations)))
    return None


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration(text: Optional[str]) -> Optional[float]:
    """Seconds in an OpenAI rate-limit duration ("1m30.5s", "250ms"), or None."""
    if not text:
        return None
    parts = _DURATION_RE.findall(text.strip())
    if not parts or "".join(n + u for n, u in parts) != text.strip():
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(n) * scale[u] for n, u in parts)


# ---------------------------------------------------------------------------
# Clients


class ModelClient:
    """Shared bookkeeping for the real and fake clients."""

    fake = False

    def __init__(
        self,
        *,
        spend: Optional[SpendTracker] = None,
        raw_dir: Optional[Path] = None,
        concurrency: int = 16,
        pricing: Optional[dict] = None,
    ):
        self.spend = spend or SpendTracker()
        self.raw_dir = raw_dir
        self.records: list[CallRecord] = []
        self.pricing = pricing or load_pricing()
        self._semaphore = asyncio.Semaphore(concurrency)
        self._counter = 0
        self._counter_lock = threading.Lock()

    def _next_call_id(self) -> str:
        with self._counter_lock:
            self._counter += 1
            return f"c{self._counter:06d}"

    def _save_raw(self, call_id: str, payload: dict, response: Any) -> Optional[str]:
        if self.raw_dir is None:
            return None
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / f"{call_id}.json"
        path.write_text(json.dumps({"request": payload, "response": response}, ensure_ascii=False), encoding="utf-8")
        return path.name

    async def chat(
        self,
        *,
        purpose: str,
        model: str,
        messages: list[dict],
        system: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        provider: Optional[dict] = None,
        seed: Optional[int] = None,
        extra: Optional[dict] = None,
        fake_hint: Any = None,
    ) -> tuple[dict, CallRecord]:
        payload = build_payload(
            model=model, messages=messages, system=system, tools=tools, provider=provider, seed=seed, extra=extra
        )
        record = CallRecord(
            call_id=self._next_call_id(),
            purpose=purpose,
            model=model,
            request_sha256=sha256_hex(canonical_json(payload)),
            seed=seed,
            context=dict(CALL_CONTEXT.get()),
            fake=self.fake,
        )
        async with self._semaphore:
            # Checked after acquiring a slot, so calls queued behind the cap never start.
            self.spend.check()
            data = await self._send(payload, record, fake_hint)
        for key, value in _usage_fields(data).items():
            setattr(record, key, value)
        if record.cost is None and record.prompt_tokens is not None:
            record.cost = estimate_cost(
                model, record.prompt_tokens or 0, record.completion_tokens or 0, self.pricing, cached_tokens=record.cached_tokens or 0
            )
            record.cost_estimated = True
        record.response_id = data.get("id")
        record.returned_model = data.get("model")
        record.provider = data.get("provider")
        record.system_fingerprint = data.get("system_fingerprint")
        choice = (data.get("choices") or [{}])[0]
        record.finish_reason = choice.get("finish_reason")
        record.raw_path = self._save_raw(record.call_id, payload, data)
        self.spend.charge(record.cost)
        self.records.append(record)
        return data, record

    async def _send(self, payload: dict, record: CallRecord, fake_hint: Any) -> dict:  # pragma: no cover
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class OpenRouterClient(ModelClient):
    """Real, paid calls to OpenRouter. Construct only after ``--confirm-spend``."""

    KEY_NAME = "OPENROUTER_API_KEY"

    def __init__(
        self,
        *,
        confirm_spend: bool,
        api_key: Optional[str] = None,
        timeout_s: float = TIMEOUT_S,
        max_retries: int = 5,
        base_url: str = OpenRouterBaseURL,
        rpm: Optional[float] = DEFAULT_RPM,
        **kwargs: Any,
    ):
        if confirm_spend is not True:
            raise SpendNotConfirmed("refusing to create a paid OpenRouter client without --confirm-spend")
        super().__init__(**kwargs)
        if api_key is None:
            api_key = self._default_key()
        if not (api_key or "").strip():
            raise SpendNotConfirmed(f"{self.KEY_NAME} is not set (in .env or the environment)")
        self._headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout_s)
        self.rpm = rpm
        self._limiters: dict[str, RateLimiter] = {}

    def _default_key(self) -> Optional[str]:
        from server.config import get_settings

        return get_settings().openrouter_api_key

    def _wire(self, payload: dict) -> dict:
        """The request body actually sent."""
        return payload

    def _finish(self, data: dict) -> dict:
        return data

    def _fatal_429(self, response: "httpx.Response") -> bool:
        return False

    def limiter(self, model: str) -> RateLimiter:
        if model not in self._limiters:
            self._limiters[model] = RateLimiter(self.rpm)
        return self._limiters[model]

    async def _send(self, payload: dict, record: CallRecord, fake_hint: Any) -> dict:
        url = f"{self.base_url}/chat/completions"
        last_error = "unknown error"
        limiter = self.limiter(payload["model"])
        wire = self._wire(payload)
        for attempt in range(self.max_retries + 1):
            record.attempts = attempt + 1
            await limiter.acquire()
            started = time.monotonic()
            retryable = False
            wait_s: Optional[float] = None
            try:
                response = await self._http.post(url, headers=self._headers, json=wire)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                retryable = True
            else:
                record.latency_ms = (time.monotonic() - started) * 1000.0
                if response.status_code == 429 and self._fatal_429(response):
                    record.error = f"HTTP 429: {response.text[:500]}"
                    self._save_raw(record.call_id, payload, {"status": 429, "body": response.text})
                    raise ApiError(record.error)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    retryable = True
                    if response.status_code == 429:
                        # Wait for the limit to reset (shared by every call to this model), not a short backoff.
                        wait_s = rate_limit_wait(response) or float(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
                        limiter.pause(wait_s)
                elif response.status_code >= 400:
                    record.error = f"HTTP {response.status_code}: {response.text[:500]}"
                    self._save_raw(record.call_id, payload, {"status": response.status_code, "body": response.text})
                    raise ApiError(record.error)
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        last_error = "response was not JSON"
                        retryable = True
                    else:
                        error = data.get("error") if isinstance(data, dict) else None
                        if error:
                            code = error.get("code") if isinstance(error, dict) else None
                            last_error = f"provider error: {json.dumps(error)[:300]}"
                            if code in (429,) or (isinstance(code, int) and code >= 500) or code is None:
                                retryable = True
                            else:
                                record.error = last_error
                                raise ApiError(last_error)
                        else:
                            return self._finish(data)
            if retryable and attempt < self.max_retries:
                if wait_s is None:  # a 429 already paused the limiter, which acquire() waits out
                    await asyncio.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
                continue
            break
        record.error = last_error
        self._save_raw(record.call_id, payload, {"error": last_error})
        raise ApiError(f"{last_error} (after {record.attempts} attempts)")

    async def aclose(self) -> None:
        await self._http.aclose()


class OpenAIClient(OpenRouterClient):
    """Real, paid calls straight to OpenAI's API, for runs configured with ``models.api: "openai"``.

    ``model_ids`` maps the config's model names to OpenAI snapshot ids (the pin). The
    OpenRouter-only keys are dropped and ``max_tokens`` becomes ``max_completion_tokens``.
    """

    KEY_NAME = "OPENAI_API_KEY"

    def __init__(self, *, model_ids: dict[str, str], base_url: str = OPENAI_BASE_URL, rpm: Optional[float] = OPENAI_DEFAULT_RPM, **kwargs: Any):
        super().__init__(base_url=base_url, rpm=rpm, **kwargs)
        self.model_ids = dict(model_ids)

    def _default_key(self) -> Optional[str]:
        return openai_key()

    def _wire(self, payload: dict) -> dict:
        return openai_wire_payload(payload, self.model_ids)

    def _finish(self, data: dict) -> dict:
        data.setdefault("provider", "OpenAI")
        return data

    def _fatal_429(self, response: "httpx.Response") -> bool:
        # Out of credit, not a rate limit: retrying can't help.
        return "insufficient_quota" in response.text


def openai_wire_payload(payload: dict, model_ids: dict[str, str]) -> dict:
    wire = {k: v for k, v in payload.items() if k not in OPENROUTER_ONLY_KEYS}
    wire["model"] = model_ids.get(payload["model"], payload["model"])
    if "max_tokens" in wire:
        wire["max_completion_tokens"] = wire.pop("max_tokens")
    return wire


def openai_key() -> Optional[str]:
    import server.config  # noqa: F401  (loads .env into the environment)

    return (os.environ.get("OPENAI_API_KEY") or "").strip() or None


async def check_openai_pins(model_ids: dict[str, str], api_key: str, base_url: str = OPENAI_BASE_URL) -> tuple[dict[str, str], list[str]]:
    """Each configured snapshot must be available to the key (``GET /models``, free)."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
    if response.status_code != 200:
        return {}, [f"OpenAI GET /models returned HTTP {response.status_code}: {response.text[:200]}"]
    available = {entry["id"] for entry in response.json().get("data", [])}
    return pin_problems(model_ids, available)


def pin_problems(model_ids: dict[str, str], available: set[str]) -> tuple[dict[str, str], list[str]]:
    observed, problems = {}, []
    for name, snapshot in model_ids.items():
        observed[name] = snapshot
        if snapshot not in available:
            family = name.split("/")[-1]
            similar = sorted(m for m in available if m.startswith(family))
            problems.append(f"{snapshot} is not available to this OpenAI key; {family} models it can use: {similar or 'none'}")
    return observed, problems


async def fetch_model_listing(base_url: str = OpenRouterBaseURL) -> dict[str, dict]:
    """``GET /models`` (free, no key) as {model id: entry}. Only used by confirmed runs."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models")
        response.raise_for_status()
        return {entry["id"]: entry for entry in response.json().get("data", [])}


def check_pins(listing: dict[str, dict], expected: dict[str, str]) -> tuple[dict[str, Optional[str]], list[str]]:
    """Compare each model's ``canonical_slug`` with the expected one. Returns (observed, problems)."""
    observed: dict[str, Optional[str]] = {}
    problems: list[str] = []
    for model, slug in expected.items():
        entry = listing.get(model)
        observed[model] = entry.get("canonical_slug") if entry else None
        if entry is None:
            problems.append(f"{model} is not listed on OpenRouter")
        elif slug and observed[model] != slug:
            problems.append(f"{model} now resolves to {observed[model]}, expected {slug}")
    return observed, problems


# ---------------------------------------------------------------------------
# Fake model

Responder = Callable[[dict, Any], dict]

_AGENT_RE = re.compile(r'<agent name="([^"]*)" />')
_NEW_MSG_RE = re.compile(r"<(new_user_message|new_agent_message)>\n(.*)\n</\1>", re.S)


def fake_usage(payload: dict, completion_tokens: int, model: str, pricing: dict) -> dict:
    prompt_tokens = math.ceil(len(json.dumps(payload.get("messages", []), ensure_ascii=False)) / 4)
    if payload.get("tools"):
        prompt_tokens += math.ceil(len(json.dumps(payload["tools"])) / 4)
    cost = estimate_cost(model, prompt_tokens, completion_tokens, pricing) if model in pricing["prices_per_million"] else 0.0
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost": cost}


def fake_message(content: str = "", tool_calls: Optional[list[dict]] = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def fake_tool_call(call_id: str, name: str, arguments: Any) -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


def fake_routing_responder(payload: dict, hint: Any) -> dict:
    """A crude, deterministic stand-in for the interaction model.

    First iteration: acknowledge and delegate (reuse the roster agent sharing the most
    name tokens with the message, else create one named after the message); agent
    messages get a summary only. Later iterations end the loop with no tool calls.
    """
    messages = payload["messages"]
    if any(m.get("role") == "assistant" for m in messages):
        return fake_message("")
    user = next(m for m in messages if m.get("role") == "user")["content"]
    match = _NEW_MSG_RE.search(user)
    kind, text = (match.group(1), match.group(2)) if match else ("new_user_message", user)
    h = int(sha256_hex(f"{payload.get('seed')}|{text}")[:8], 16)
    if kind == "new_agent_message":
        return fake_message("", [fake_tool_call("call_0", "send_message_to_user", {"message": "fyi: " + text[:60]})])
    names = [unescape(n) for n in _AGENT_RE.findall(user)]
    words = slug_tokens(text)
    scored = sorted(((len(slug_tokens(n) & words), -i, n) for i, n in enumerate(names)), reverse=True)
    if scored and scored[0][0] > 0:
        agent_name = scored[0][2]
    elif h % 7 == 0:
        return fake_message("", [fake_tool_call("call_0", "send_message_to_user", {"message": "ha, sure"})])
    else:
        picked = sorted(words, key=lambda w: (-len(w), w))[:3] or ["task"]
        agent_name = " ".join(w.capitalize() for w in picked)
    calls = [
        fake_tool_call("call_0", "send_message_to_user", {"message": "on it"}),
        fake_tool_call("call_1", "send_message_to_agent", {"agent_name": agent_name, "instructions": text}),
    ]
    if h % 23 == 0:
        calls.append(fake_tool_call("call_2", "send_message_to_agent", '{"agent_name": "broken'))
    return fake_message("", calls)


def fake_summarizer_responder(payload: dict, hint: Any) -> dict:
    content = payload["messages"][-1]["content"]
    count = content.count("\n[")
    return fake_message(
        "Summary generated: 2026-10-20 12:00 (user timezone)\n\n"
        f"Timeline & Commitments:\n- No items.\n\nPending & Follow-ups:\n- {count} log lines merged.\n\n"
        "Routines & Recurring:\n- No items.\n\nPreferences & Profile:\n- No items.\n\nContext & Notes:\n- Fake summary."
    )


def fake_probe_responder(payload: dict, hint: Any) -> dict:
    return fake_message("")


class FakeClient(ModelClient):
    """Deterministic responses, synthetic usage, no network. Results are marked fake."""

    fake = True

    def __init__(self, responders: Optional[dict[str, Responder]] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.responders: dict[str, Responder] = {
            "routing": fake_routing_responder,
            "naming": fake_routing_responder,
            "summarizer": fake_summarizer_responder,
            "fixture_summarizer": fake_summarizer_responder,
            "label_summarizer": fake_summarizer_responder,
            "token_probe": fake_probe_responder,
        }
        self.responders.update(responders or {})

    def register(self, purpose: str, responder: Responder) -> None:
        self.responders[purpose] = responder

    async def _send(self, payload: dict, record: CallRecord, fake_hint: Any) -> dict:
        responder = self.responders.get(record.purpose)
        if responder is None:
            raise ApiError(f"fake model has no responder for purpose {record.purpose!r}")
        record.attempts = 1
        message = responder(payload, fake_hint)
        completion_tokens = 1 if payload.get("max_tokens") == 1 else max(
            1, math.ceil(len(json.dumps(message, ensure_ascii=False)) / 4)
        )
        record.latency_ms = 400.0 + int(record.request_sha256[:4], 16) % 800
        finish = "tool_calls" if isinstance(message, dict) and message.get("tool_calls") else "stop"
        return {
            "id": f"fake-{record.call_id}",
            "model": f"{payload['model']}-fake",
            "provider": "Fake",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": fake_usage(payload, completion_tokens, payload["model"], self.pricing),
        }


def message_content(response: dict) -> str:
    choice = (response.get("choices") or [{}])[0]
    return ((choice.get("message") or {}).get("content") or "").strip()


__all__ = [
    "ApiError",
    "CALL_CONTEXT",
    "CallRecord",
    "FakeClient",
    "ModelClient",
    "OpenRouterClient",
    "RateLimiter",
    "DEFAULT_RPM",
    "SpendCapReached",
    "SpendNotConfirmed",
    "SpendTracker",
    "build_payload",
    "check_pins",
    "estimate_cost",
    "OpenAIClient",
    "OPENAI_DEFAULT_RPM",
    "check_openai_pins",
    "openai_key",
    "openai_wire_payload",
    "parse_duration",
    "pin_problems",
    "fetch_model_listing",
    "load_pricing",
    "message_content",
    "production_view",
]
