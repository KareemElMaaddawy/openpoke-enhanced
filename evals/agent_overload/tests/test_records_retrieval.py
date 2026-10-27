"""records_retrieval v1: stub parity, names_only unchanged, carried extras, fake end to end, probe, embeddings.

No API calls: everything runs on the fake model or a mocked HTTP transport, and nothing is
written to the real spend ledger or the real method cache.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx

from evals.agent_overload import retrieval_probe, run
from evals.agent_overload.harness import llm
from evals.agent_overload.harness.methods.base import AgentView, Entry, RoutingInput, WorkItem
from evals.agent_overload.harness.methods.records_retrieval import (
    MethodConfigError,
    MethodParams,
    RecordsRetrievalMethod,
    RecordsToolStubs,
    RecordsTurnRecorder,
    created_agent_id,
    prepare_plan,
    record_view,
)
from evals.agent_overload.harness.runner import _carried_work
from evals.agent_overload.harness.scoring import DistinctDelegation
from evals.agent_overload.harness.state import AgentRecord as HarnessAgent
from evals.agent_overload.harness.state import RoutingState
from evals.agent_overload.harness.util import EVAL_ROOT
from server.agents.interaction_agent import tools_records
from server.services.agents.records import AgentRecordStore
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import AgentRoster
from server.services.routing import RetrievalParams

CONFIGS = EVAL_ROOT / "configs"
NOW = "2026-10-26 10:00:00"

# names_only fake-model dev-quick run on the frozen v1 fixtures, recorded before the
# records_retrieval interface additions (run ids and call ids removed).
NAMES_ONLY_GOLDEN = (372, "410bc25aedac630a4cb0453eafff2797cd18af0ba91ee9428b153b5dd9b6251d")


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = fn(*args)
    return code, out.getvalue()


def read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as handle:
        return [json.loads(line) for line in handle]


def fake_run(config: Path, profile: str, tmp: str) -> Path:
    code, out = quiet(
        run.main,
        ["--config", str(config), "--profile", profile, "--fake-model", "--results-dir", tmp, "--ledger", str(Path(tmp) / "ledger.jsonl")],
    )
    assert code == 0, out[-3000:]
    return next(p for p in Path(tmp).iterdir() if p.is_dir())


class NamesOnlyUnchangedTest(unittest.TestCase):
    def test_fake_run_turns_identical_to_before_the_interface_additions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = fake_run(CONFIGS / "baseline_names_only.json", "dev-quick", tmp)
            rows = read_gz(run_dir / "turns.jsonl.gz")
        for row in rows:
            row.pop("run_id", None)
            row.pop("call_ids", None)
        blob = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        self.assertEqual((len(rows), hashlib.sha256(blob.encode()).hexdigest()), NAMES_ONLY_GOLDEN)


class StubParityTest(unittest.TestCase):
    """Each records stub returns the same ToolResult payload as the real tool on equivalent state."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.store = AgentRecordStore(base / "agents.json")
        self.roster = AgentRoster(base / "roster.json")
        self.logs = ExecutionAgentLogStore(base / "logs")
        for target, value in (
            ("get_agent_records", lambda: self.store),
            ("get_agent_roster", lambda: self.roster),
            ("get_execution_agent_logs", lambda: self.logs),
            ("_dispatch", lambda *args: True),
            ("_now", lambda: NOW),
        ):
            patcher = mock.patch.object(tools_records, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.keith = self.store.create("Email Keith", "Emails with Keith.", NOW)
        self.aws = self.store.create("AWS Invoice Lookup", "Finds AWS invoices.", NOW)

    def stubs(self) -> RecordsToolStubs:
        views = [
            record_view(AgentView(r.agent_id, r.name, (WorkItem("first task", "done"),), NOW, NOW), {})
            for r in self.store.all()
        ]
        return RecordsToolStubs(RecordsTurnRecorder(views))

    def both(self, name: str, arguments: dict) -> tuple:
        stub = self.stubs().handle_tool_call(name, dict(arguments))
        real = tools_records.handle_records_tool_call(name, dict(arguments))
        return stub, real

    def assert_same(self, name: str, arguments: dict, ignore_agent_id: bool = False) -> None:
        stub, real = self.both(name, arguments)
        self.assertEqual(stub.success, real.success)
        stub_payload, real_payload = dict(stub.payload), dict(real.payload)
        if ignore_agent_id:
            stub_payload.pop("agent_id"), real_payload.pop("agent_id")
        self.assertEqual(stub_payload, real_payload)

    def test_reuse_by_id(self):
        self.assert_same("send_message_to_agent", {"agent_id": self.aws.agent_id, "instructions": "Was it paid?"})

    def test_name_passed_as_id(self):
        self.assert_same("send_message_to_agent", {"agent_id": "email keith", "instructions": "Reply"})

    def test_unknown_id(self):
        self.assert_same("send_message_to_agent", {"agent_id": "ag_00000000", "instructions": "Lost"})

    def test_create(self):
        self.assert_same("create_agent", {"name": "Flight Booking", "purpose": "Books flights.", "instructions": "Find SFO-JFK"}, ignore_agent_id=True)

    def test_create_collision(self):
        self.assert_same("create_agent", {"name": "email-keith", "purpose": "Duplicate", "instructions": "Reply"})

    def test_create_empty_name(self):
        self.assert_same("create_agent", {"name": "  ", "purpose": "x", "instructions": "y"})

    def test_create_long_name_is_cut(self):
        self.assert_same("create_agent", {"name": "N" * 80, "purpose": "x", "instructions": "y"}, ignore_agent_id=True)

    def test_missing_arguments_name_the_production_function(self):
        self.assert_same("create_agent", {"name": "Flights", "instructions": "y"})
        self.assert_same("send_message_to_agent", {"agent_name": "Email Keith", "instructions": "y"})

    def test_shared_tools_and_unknown_tool(self):
        with mock.patch("server.agents.interaction_agent.tools.get_conversation_log"):
            self.assert_same("wait", {"reason": "dup"})
            self.assert_same("send_message_to_user", {"message": "hi"})
        self.assert_same("reacttomessage", {})

    def test_empty_purpose_falls_back_the_same_way(self):
        instructions = "Find the latest invoice from AWS " + "and summarize it " * 20
        stubs = self.stubs()
        result = stubs.handle_tool_call("create_agent", {"name": "AWS Invoices", "purpose": "", "instructions": instructions})
        real = tools_records.handle_records_tool_call("create_agent", {"name": "AWS Invoices", "purpose": "", "instructions": instructions})
        self.assertTrue(result.success and real.success)
        stored = self.store.get(real.payload["agent_id"])
        self.assertEqual(stubs.r.delegations[0].extra["purpose"], stored.purpose)
        self.assertEqual(stubs.r.purpose_fallbacks, 1)

    def test_stub_bookkeeping(self):
        stubs = self.stubs()
        stubs.handle_tool_call("create_agent", {"name": "Flight Booking", "purpose": "Books flights.", "instructions": "a"})
        stubs.handle_tool_call("send_message_to_agent", {"agent_id": created_agent_id("Flight Booking"), "instructions": "b"})
        stubs.handle_tool_call("create_agent", {"name": "flight booking", "purpose": "again", "instructions": "c"})
        stubs.handle_tool_call("send_message_to_agent", {"agent_id": "nobody", "instructions": "d"})
        recorder = stubs.r
        self.assertEqual([d.agent_key for d in recorder.delegations], ["new:Flight Booking", "new:Flight Booking"])
        self.assertEqual(recorder.delegations[0].extra, {"purpose": "Books flights."})
        self.assertEqual(recorder.rejected_creates, [{"name": "flight booking", "existing_agent_id": created_agent_id("Flight Booking")}])
        self.assertEqual([c["error"] for c in recorder.invalid_calls], ["unknown agent_id"])


class CarriedExtraTest(unittest.TestCase):
    def test_purpose_written_on_turn_t_is_in_the_view_on_turn_t_plus_1(self):
        seeded = HarnessAgent("a-1", "Email Keith", "t-1", NOW, NOW, True, [WorkItem("find keith's email", "found")], 1)
        state = RoutingState(roster=[seeded], entries=[])
        state._map_counter = 1
        created = DistinctDelegation("new:Flight Booking", "Flight Booking", "Find flights", 0, 0, 0, {"purpose": "Books the user's NYC flights."})
        score = SimpleNamespace(distinct=[created], primary_key="new:Flight Booking")
        work = _carried_work(state, score, {"result_text": "Found 3 flights."})
        from evals.agent_overload.harness.state import apply_turn

        apply_turn(state, message_tag="user_message", message_text="book flights", timestamp=NOW,
                   effects=[], work=work, primary_thread="t-2", result_reply=None)
        view = state.routing_input("and the hotel?", "user", now=NOW).roster[-1]
        self.assertEqual(dict(view.extra), {"purpose": "Books the user's NYC flights."})
        self.assertEqual(record_view(view, {}).purpose, "Books the user's NYC flights.")
        self.assertEqual(record_view(state.roster[0].view(), {"a-1": "backfilled"}).purpose, "backfilled")

    def test_purpose_precedence(self):
        view = AgentView("a-1", "X", (), "", "", (("purpose", "from create"),))
        self.assertEqual(record_view(view, {"a-1": "backfilled"}).purpose, "from create")
        self.assertEqual(record_view(AgentView("a-2", "Y", (), "", ""), {}).purpose, "")


class MethodParamsTest(unittest.TestCase):
    def test_defaults_are_the_server_defaults(self):
        params = MethodParams.parse({})
        self.assertEqual(params.retrieval, RetrievalParams())
        self.assertEqual((params.seed_purposes, params.embedding_model, params.embedding_dimensions, params.scorer),
                         ("backfill", "openai/text-embedding-3-small", 512, "interaction_agent"))

    def test_rejects_unknown_values(self):
        for bad in ({"kk": 8}, {"seed_purposes": "some"}, {"scorer": {"name": "jev"}}):
            with self.subTest(params=bad), self.assertRaises(MethodConfigError):
                MethodParams.parse(bad)

    def test_configs_parse(self):
        for name in ("v1_records_full.json", "v1_records_retrieval.json"):
            config = json.loads((CONFIGS / name).read_text())
            MethodParams.parse(config["method"]["params"])
            baseline = json.loads((CONFIGS / "baseline_names_only.json").read_text())
            self.assertEqual({k: v for k, v in config.items() if k != "method"}, {k: v for k, v in baseline.items() if k != "method"})

    def test_frozen_test_config_matches_server_defaults(self):
        """Once the test config is frozen, the server must run what was measured (spec: Parameters)."""
        path = CONFIGS / "v1_records_test.json"
        if not path.exists():
            self.skipTest("v1_records_test.json is frozen after the dev runs")
        params = MethodParams.parse(json.loads(path.read_text())["method"]["params"])
        self.assertEqual(params.retrieval, RetrievalParams())


class FakeEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.retrieval_dir = fake_run(CONFIGS / "v1_records_retrieval.json", "smoke", str(root / "retrieval"))
        cls.full_dir = fake_run(CONFIGS / "v1_records_full.json", "smoke", str(root / "full"))
        cls.turns = [t for t in read_gz(cls.retrieval_dir / "turns.jsonl.gz") if t["suite"] in ("single", "sequence")]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_diagnostics_present(self):
        self.assertTrue(all(t["has_candidates"] for t in self.turns))
        self.assertTrue(all(t["agents_shown"] <= 8 for t in self.turns))
        self.assertTrue(any(t["candidate_rank"] is not None for t in self.turns))
        self.assertTrue(any(t["excluded"] for t in self.turns))

    def test_recall_computed_and_reported(self):
        metrics = json.loads((self.retrieval_dir / "metrics.json").read_text())
        self.assertIn("8", metrics["single"]["dev"]["200"]["recall_at_k"])
        self.assertIn("### Retrieval", (self.retrieval_dir / "report.md").read_text())

    def test_target_excluded_tagged_when_target_hidden(self):
        tagged = [t for t in self.turns if "target_excluded" in t["tags"]]
        self.assertTrue(tagged)
        for t in tagged:
            self.assertIn(t["primary_outcome"], ("false_spawn", "misroute"))

    def test_records_prompt_token_probe(self):
        metrics = json.loads((self.retrieval_dir / "metrics.json").read_text())
        self.assertIsNotNone(metrics["single"]["dev"]["200"]["roster_tokens_per_call_median"]["value"])

    def test_prepare_and_describe(self):
        config = json.loads((self.retrieval_dir / "config.json").read_text())
        self.assertEqual(config["harness_version"], "1.1.0")
        self.assertEqual(config["method"]["name"], "records_retrieval")
        self.assertEqual(config["method_after_run"]["prepare"]["purpose_calls"], 252)
        self.assertIsNone(config["method_after_run"]["cache"]["dir"])  # fake runs never touch the cache
        calls = read_gz(self.retrieval_dir / "calls.jsonl.gz")
        purposes = {c["purpose"] for c in calls}
        self.assertTrue({"purpose_backfill", "embed_records", "embed_query", "routing"} <= purposes)

    def test_full_config_shows_every_agent_and_has_no_candidates(self):
        turns = [t for t in read_gz(self.full_dir / "turns.jsonl.gz") if t["suite"] == "single"]
        self.assertTrue(all(t["agents_shown"] == t["N"] and not t["has_candidates"] for t in turns))
        calls = read_gz(self.full_dir / "calls.jsonl.gz")
        self.assertNotIn("embed_query", {c["purpose"] for c in calls})


class RecordsRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_route_renders_records_and_records_calls(self):
        client = llm.FakeClient()
        method = RecordsRetrievalMethod(client, model="openai/gpt-6-luna", params={"full_roster_max": 0, "k": 2}, cache_dir=None)
        agents = [
            AgentView("a-1", "Email Keith", (WorkItem("Find Keith's email about the Q3 report", "Found it."),), NOW, NOW),
            AgentView("a-2", "AWS Invoice Lookup", (WorkItem("Find the October AWS invoice", "Found: $42."),), NOW, NOW),
            AgentView("a-3", "Flight Booking", (WorkItem("Find SFO-JFK flights", "3 options."),), NOW, NOW),
        ]
        await method.prepare(agents)
        self.assertEqual(set(method.purposes), {"a-1", "a-2", "a-3"})
        inp = RoutingInput(roster=tuple(agents), summary_text="", entries=(Entry("user_message", NOW, "hi"),),
                           message_text="reply to keith about the q3 report", message_type="user", now=NOW)
        output = await method.route(inp)
        self.assertEqual(output.diagnostics["candidate_mode"], "retrieved")
        self.assertEqual(output.diagnostics["candidates"][0], "a-1")
        self.assertEqual(len(output.diagnostics["excluded"]), 1)
        self.assertEqual([d.agent_key for d in output.delegations], ["a-1"])
        purposes = [c.purpose for c in output.llm_calls]
        self.assertEqual(purposes[0], "embed_query")
        self.assertIn("routing", purposes)

        system, messages, tools = method.probe_request(inp)
        self.assertIn('<active_agents shown="0" total="0">\nNone\n</active_agents>', messages[0]["content"])
        self.assertIn("create_agent", [t["function"]["name"] for t in tools])

    async def test_spend_cap_in_embedding_stops_instead_of_falling_back(self):
        client = llm.FakeClient(spend=llm.SpendTracker(cap_usd=0.0))
        method = RecordsRetrievalMethod(client, model="openai/gpt-6-luna", params={"full_roster_max": 0, "seed_purposes": "none"}, cache_dir=None)
        inp = RoutingInput(roster=(AgentView("a-1", "X", (), NOW, NOW),), summary_text="", entries=(),
                           message_text="x", message_type="user", now=NOW)
        with self.assertRaises(llm.SpendCapReached):
            await method.route(inp)

    async def test_caches_are_written_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = [AgentView("a-1", "Email Keith", (WorkItem("Find Keith's email", "Found."),), "", "")]
            first = RecordsRetrievalMethod(llm.FakeClient(), model="openai/gpt-6-luna", cache_dir=Path(tmp))
            await first.prepare(agents)
            self.assertEqual(first.prepare_stats, {"purpose_calls": 1, "embed_calls": 1, "empty_purposes": 0})
            self.assertEqual(prepare_plan({}, agents, "openai/gpt-6-luna", Path(tmp)), [])
            second = RecordsRetrievalMethod(llm.FakeClient(), model="openai/gpt-6-luna", cache_dir=Path(tmp))
            await second.prepare(agents)
            self.assertEqual(second.prepare_stats, {"purpose_calls": 0, "embed_calls": 0, "empty_purposes": 0})
            self.assertEqual(second.purposes, first.purposes)
            self.assertIsNotNone(second.describe()["cache"]["purposes_sha256"])


class EmbedClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_fake_embeddings_are_deterministic_and_lexical(self):
        client = llm.FakeClient()
        texts = ["email keith about the report", "keith report email", "book flights to nyc"]
        vectors, record = await client.embed(purpose="embed_query", model="openai/text-embedding-3-small", inputs=texts, dimensions=64)
        again, _ = await client.embed(purpose="embed_query", model="openai/text-embedding-3-small", inputs=texts, dimensions=64)
        self.assertEqual(vectors, again)
        dot = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
        self.assertGreater(dot(vectors[0], vectors[1]), dot(vectors[0], vectors[2]))
        self.assertEqual((record.purpose, record.fake, record.completion_tokens), ("embed_query", True, 0))
        self.assertGreater(record.cost, 0)

    def _client(self, cls, handler, **kwargs):
        client = cls(confirm_spend=True, api_key="test-key", rpm=None, **kwargs)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    async def test_openai_direct_request_and_cost(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"model": "text-embedding-3-small", "data": [
                {"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}],
                "usage": {"prompt_tokens": 1000, "total_tokens": 1000}})

        client = self._client(llm.OpenAIClient, handler, model_ids={"openai/gpt-6-luna": "gpt-6-luna"})
        try:
            vectors, record = await client.embed(purpose="embed_query", model="openai/text-embedding-3-small",
                                                 inputs=["a", "b"], dimensions=2, provider={"order": ["openai"]})
        finally:
            await client.aclose()
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(str(seen[0].url), "https://api.openai.com/v1/embeddings")
        self.assertEqual(json.loads(seen[0].content),
                         {"model": "text-embedding-3-small", "input": ["a", "b"], "dimensions": 2, "encoding_format": "float"})
        self.assertTrue(record.cost_estimated)
        self.assertAlmostEqual(record.cost, 1000 * 0.02 / 1_000_000)
        self.assertEqual(record.provider, "OpenAI")

    async def test_openrouter_request_keeps_provider_and_cost(self):
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}],
                                             "usage": {"prompt_tokens": 5, "cost": 0.0000001}})

        client = self._client(llm.OpenRouterClient, handler)
        try:
            _vectors, record = await client.embed(purpose="embed_query", model="openai/text-embedding-3-small",
                                                  inputs=["a"], dimensions=2, provider={"order": ["openai"], "allow_fallbacks": False})
        finally:
            await client.aclose()
        self.assertEqual(seen[0]["provider"], {"order": ["openai"], "allow_fallbacks": False})
        self.assertEqual(seen[0]["model"], "openai/text-embedding-3-small")
        self.assertEqual((record.cost, record.cost_estimated), (0.0000001, False))

    async def test_wrong_vector_count_is_an_api_error(self):
        def handler(request):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}], "usage": {"prompt_tokens": 5}})

        client = self._client(llm.OpenAIClient, handler, model_ids={})
        try:
            with self.assertRaises(llm.ApiError):
                await client.embed(purpose="embed_query", model="openai/text-embedding-3-small", inputs=["a", "b"], dimensions=2)
        finally:
            await client.aclose()

    def test_openai_model_id(self):
        self.assertEqual(llm.openai_model_id("openai/text-embedding-3-small", {}), "text-embedding-3-small")
        self.assertEqual(llm.openai_model_id("openai/gpt-6-luna", {"openai/gpt-6-luna": "gpt-6-luna-x"}), "gpt-6-luna-x")


class ProbeTest(unittest.TestCase):
    CONFIG = str(CONFIGS / "v1_records_retrieval.json")

    def test_refuses_test_split(self):
        code, out = quiet(retrieval_probe.main, ["--config", self.CONFIG, "--split", "test", "--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("dev only", out)

    def test_dry_run_makes_no_calls(self):
        boom = mock.Mock(side_effect=AssertionError("no client may be created in a dry run"))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(retrieval_probe, "make_client", boom), \
                mock.patch.object(llm.OpenAIClient, "__init__", boom), \
                mock.patch.object(llm.OpenRouterClient, "__init__", boom), \
                mock.patch.object(RecordsRetrievalMethod, "prepare", boom):
            code, out = quiet(retrieval_probe.main, ["--config", self.CONFIG, "--dry-run", "--ledger", str(Path(tmp) / "l.jsonl")])
            self.assertFalse((Path(tmp) / "l.jsonl").exists())
        self.assertEqual(code, 0)
        self.assertIn("dry run: no API was called.", out)
        boom.assert_not_called()

    def test_fake_probe_reports_recall_and_pin_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--config", self.CONFIG, "--fake-model", "--limit", "12", "--sizes", "50", "200",
                    "--set", "max_pinned=2", "--results-dir", tmp, "--ledger", str(Path(tmp) / "l.jsonl")]
            code, out = quiet(retrieval_probe.main, args)
            self.assertEqual(code, 0, out[-2000:])
            probe_dir = next(p for p in Path(tmp).iterdir() if p.is_dir())
            result = json.loads((probe_dir / "probe.json").read_text())
            self.assertFalse((Path(tmp) / "l.jsonl").exists())
        self.assertEqual(result["meta"]["params"]["max_pinned"], 2)
        self.assertEqual(set(result["summary"]["by"]["N"]), {"50", "200"})
        self.assertEqual(set(result["summary"]["overall"]["recall_at"]), {"1", "3", "5", "8", "10", "12", "20"})
        self.assertIn("pin_only_share_of_hits_at_k", result["summary"]["overall"])


if __name__ == "__main__":
    unittest.main()
