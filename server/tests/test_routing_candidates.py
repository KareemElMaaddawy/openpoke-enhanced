"""Candidate selection: short-circuits, pins, queries, BM25, RRF, index staleness, failure."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from server.services.agents.records import WorkSnippet
from server.services.agents.text import retrieval_text
from server.services.routing.candidates import (
    RANKED_MAX,
    EntryView,
    RecordView,
    select_candidates,
)
from server.services.routing.embeddings import (
    EmbeddingError,
    EmbeddingIndex,
    OpenRouterEmbedder,
    normalize,
)
from server.services.routing.lexical import bm25_scores, tokenize
from server.services.routing.params import RetrievalParams
from server.services.routing.pins import find_pins
from server.services.routing.query import build_queries
from server.services.routing.scorer import InteractionAgentScorer, ScoringInput
from server.tests.fakes import FakeEmbedder

# Always retrieve unless a test says otherwise.
RETRIEVE = RetrievalParams(full_roster_max=0)


def view(agent_id, name, purpose="", work=(), last_active="2026-10-01 09:00:00", aliases=()):
    return RecordView(
        agent_id=agent_id,
        name=name,
        purpose=purpose,
        recent_work=tuple(WorkSnippet(i, r, last_active) for i, r in work),
        last_active=last_active,
        task_count=len(work),
        aliases=tuple(aliases),
    )


def filler(n, start=0):
    return [view(f"ag_fill{i:04d}", f"Filler Agent {i}", last_active="") for i in range(start, start + n)]


class ShortCircuitTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty(self) -> None:
        embedder = FakeEmbedder()
        result = await select_candidates([], "hi", "user", [], RETRIEVE, embedder)
        self.assertEqual(result.mode, "empty")
        self.assertEqual((result.shown, result.ranked, result.excluded), ([], [], []))
        self.assertEqual(embedder.calls, [])

    async def test_full_roster_at_or_below_threshold(self) -> None:
        records = filler(3)
        embedder = FakeEmbedder()
        params = RetrievalParams(full_roster_max=3)
        result = await select_candidates(records, "hi", "user", [], params, embedder)
        ids = [r.agent_id for r in records]
        self.assertEqual(result.mode, "full")
        self.assertEqual(result.shown, ids)
        self.assertEqual(result.ranked, ids)
        self.assertEqual(result.excluded, [])
        self.assertEqual(result.embed_calls, 0)
        self.assertEqual(embedder.calls, [])

    async def test_retrieves_above_threshold(self) -> None:
        result = await select_candidates(filler(4), "hi", "user", [], RetrievalParams(full_roster_max=3), FakeEmbedder())
        self.assertEqual(result.mode, "retrieved")

    async def test_full_roster_max_zero_always_retrieves(self) -> None:
        result = await select_candidates(filler(1), "hi", "user", [], RETRIEVE, FakeEmbedder())
        self.assertEqual(result.mode, "retrieved")
        self.assertEqual(result.shown, ["ag_fill0000"])


class PinsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            view("ag_keith", "Email Keith", aliases=("keith-mail",)),
            view("ag_aws", "AWS Invoice Lookup"),
            view("ag_flight", "Flight Booking"),
            view("ag_cal", "Calendar Sync"),
        ]

    def test_pins_from_execution_result_lines(self) -> None:
        message = "[SUCCESS] AWS Invoice Lookup: Found it.\nsecond line\n[FAILED] Email Keith: Timed out."
        pins = find_pins(message, "agent", [], self.records, RETRIEVE)
        self.assertEqual(pins, ["ag_aws", "ag_keith"])

    def test_user_message_lines_are_not_parsed(self) -> None:
        self.assertEqual(find_pins("[SUCCESS] AWS Invoice Lookup: x", "user", [], self.records, RETRIEVE), [])

    def test_pins_from_recent_result_lines_newest_first(self) -> None:
        entries = [
            EntryView("agent_message", "[SUCCESS] Calendar Sync: synced"),
            EntryView("user_message", "thanks"),
            EntryView("agent_message", "[SUCCESS] Flight Booking: booked"),
            EntryView("poke_reply", "[SUCCESS] Email Keith: not an agent message"),
        ]
        pins = find_pins("reply to that", "user", entries, self.records, RETRIEVE)
        self.assertEqual(pins, ["ag_flight", "ag_cal"])

    def test_lookback_limits_scanned_messages(self) -> None:
        entries = [EntryView("agent_message", "[SUCCESS] Calendar Sync: synced")]
        entries += [EntryView("agent_message", "no result lines here")] * 3
        self.assertEqual(find_pins("ok", "user", entries, self.records, RETRIEVE), [])

    def test_deduped_and_capped(self) -> None:
        message = "\n".join(
            [
                "[SUCCESS] Email Keith: a",
                "[SUCCESS] email keith: b",       # slug match, same agent
                "[SUCCESS] keith-mail: c",        # alias, same agent
                "[SUCCESS] AWS Invoice Lookup: d",
                "[SUCCESS] Unknown Agent: e",
                "[SUCCESS] Flight Booking: f",
                "[SUCCESS] Calendar Sync: g",
            ]
        )
        pins = find_pins(message, "agent", [], self.records, RETRIEVE)
        self.assertEqual(pins, ["ag_keith", "ag_aws", "ag_flight"])
        self.assertEqual(find_pins(message, "agent", [], self.records, replace(RETRIEVE, use_pins=False)), [])

    def test_email_alert_gets_only_recent_result_pins(self) -> None:
        entries = [EntryView("agent_message", "[SUCCESS] Email Keith: found the thread")]
        alert = "Important email watcher notification:\nNew email from AWS billing."
        self.assertEqual(find_pins(alert, "agent", entries, self.records, RETRIEVE), ["ag_keith"])


class QueryTest(unittest.TestCase):
    def test_strips_result_prefixes(self) -> None:
        queries = build_queries("[SUCCESS] AWS Invoice Lookup: Found it.\nMore detail", "agent", [], RETRIEVE)
        self.assertEqual(queries, ["Found it.\nMore detail"])

    def test_strips_email_alert_prefix(self) -> None:
        queries = build_queries("Important email watcher notification:\nKeith wrote back", "agent", [], RETRIEVE)
        self.assertEqual(queries, ["Keith wrote back"])

    def test_context_query_uses_previous_user_message(self) -> None:
        entries = [EntryView("user_message", "find the aws invoice"), EntryView("poke_reply", "on it")]
        self.assertEqual(
            build_queries("reply to that", "user", entries, RETRIEVE),
            ["reply to that", "find the aws invoice\nreply to that"],
        )
        off = replace(RETRIEVE, query_with_previous_user_message=False)
        self.assertEqual(build_queries("reply to that", "user", entries, off), ["reply to that"])

    def test_queries_capped_at_2000_chars(self) -> None:
        entries = [EntryView("user_message", "p" * 1500)]
        q_msg, q_ctx = build_queries("m" * 2500, "user", entries, RETRIEVE)
        self.assertEqual((len(q_msg), len(q_ctx)), (2000, 2000))


class LexicalTest(unittest.IsolatedAsyncioTestCase):
    def test_tokenize_drops_stopwords(self) -> None:
        self.assertEqual(tokenize("Can you please email Keith re: the Q3 report?"), ["email", "keith", "q3", "report"])

    def test_bm25_prefers_shared_proper_noun(self) -> None:
        docs = [tokenize("Email to Sharanjeet about the offsite"), tokenize("Email Keith about the Q3 report")]
        scores = bm25_scores(tokenize("draft a reply to Keith"), docs)
        self.assertEqual(scores[0], 0.0)
        self.assertGreater(scores[1], 0.0)

    async def test_lexical_only_selection_ranks_proper_noun_first(self) -> None:
        records = filler(10) + [
            view("ag_sharan", "Email to Sharanjeet", "Emails with Sharanjeet about the offsite."),
            view("ag_keith", "Email Keith", "Emails with Keith about the Q3 report."),
        ]
        params = replace(RETRIEVE, use_semantic=False, k=3)
        result = await select_candidates(records, "draft a reply to Keith", "user", [], params)
        self.assertEqual(result.shown[0], "ag_keith")
        self.assertEqual(result.mode, "retrieved")
        self.assertIsNone(result.scores["ag_keith"]["sem"])
        self.assertGreater(result.scores["ag_keith"]["lex"], 0)
        self.assertEqual(result.scores["ag_sharan"]["lex"], 0.0)


class FusionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Semantic order A > B > C > D; lexical matches only C ("zebra" twice) and D ("zebra" once).
        self.records = [
            view("ag_a", "Alpha", "aaa"),
            view("ag_b", "Bravo", "bbb"),
            view("ag_c", "Charlie", "zebra zebra"),
            view("ag_d", "Delta", "zebra"),
        ]
        query = "zebra"
        texts = {r.agent_id: retrieval_text(r) for r in self.records}
        self.embedder = FakeEmbedder(
            dimensions=2,
            vectors={
                query: [1.0, 0.0],
                texts["ag_a"]: [1.0, 0.0],
                texts["ag_b"]: [0.9, 0.1],
                texts["ag_c"]: [0.5, 0.5],
                texts["ag_d"]: [0.1, 0.9],
            },
        )
        self.query = query

    async def test_rrf_combines_channels(self) -> None:
        result = await select_candidates(self.records, self.query, "user", [], RETRIEVE, self.embedder)
        # rrf: C = 1/63 + 1/61, D = 1/64 + 1/62, A = 1/61, B = 1/62
        self.assertEqual(result.ranked, ["ag_c", "ag_d", "ag_a", "ag_b"])
        self.assertAlmostEqual(result.scores["ag_c"]["rrf"], 1 / 63 + 1 / 61)
        self.assertAlmostEqual(result.scores["ag_a"]["rrf"], 1 / 61)
        self.assertEqual(result.embed_calls, 1)

    async def test_weights_change_order(self) -> None:
        params = replace(RETRIEVE, w_lex=0.0)
        result = await select_candidates(self.records, self.query, "user", [], params, self.embedder)
        self.assertEqual(result.ranked, ["ag_a", "ag_b", "ag_c", "ag_d"])

    async def test_ties_break_by_last_active_then_agent_id(self) -> None:
        records = [
            view("ag_3", "Three", last_active="2026-10-01 09:00:00"),
            view("ag_2", "Two", last_active="2026-10-05 09:00:00"),
            view("ag_1", "One", last_active="2026-10-01 09:00:00"),
            view("ag_0", "Zero", last_active=""),
            view("ag_9", "Match", "zebra", last_active=""),
        ]
        params = replace(RETRIEVE, use_semantic=False)
        result = await select_candidates(records, "zebra", "user", [], params)
        self.assertEqual(result.ranked, ["ag_9", "ag_2", "ag_1", "ag_3", "ag_0"])

    async def test_recency_channel_when_weighted(self) -> None:
        records = [
            view("ag_old", "Old", last_active="2026-09-01 09:00:00"),
            view("ag_new", "New", last_active="2026-10-20 09:00:00"),
            view("ag_none", "Unknown", last_active=""),
        ]
        params = replace(RETRIEVE, use_semantic=False, use_lexical=False, w_rec=1.0)
        result = await select_candidates(records, "anything", "user", [], params)
        self.assertEqual(result.ranked, ["ag_new", "ag_old", "ag_none"])
        self.assertEqual(result.scores["ag_none"]["rrf"], 0)

    async def test_pins_come_first_and_count_inside_k(self) -> None:
        message = "[SUCCESS] Delta: done\n[SUCCESS] Bravo: done"
        params = replace(RETRIEVE, k=3)
        result = await select_candidates(self.records, message, "agent", [], params, self.embedder)
        self.assertEqual(result.pinned, ["ag_d", "ag_b"])
        self.assertEqual(result.shown[:2], ["ag_d", "ag_b"])
        self.assertEqual(len(result.shown), 3)
        self.assertEqual(len(result.ranked), 4)


class OutputShapeTest(unittest.IsolatedAsyncioTestCase):
    async def test_shown_plus_excluded_is_all_active_and_ranked_capped(self) -> None:
        records = filler(40) + [view("ag_keith", "Email Keith", "Emails with Keith.")]
        result = await select_candidates(records, "email keith", "user", [], RETRIEVE, FakeEmbedder())
        all_ids = {r.agent_id for r in records}
        self.assertEqual(len(result.shown), RETRIEVE.k)
        self.assertEqual(set(result.shown) | set(result.excluded), all_ids)
        self.assertEqual(set(result.shown) & set(result.excluded), set())
        self.assertEqual(len(result.ranked), RANKED_MAX)
        self.assertEqual(result.shown, result.ranked[: RETRIEVE.k])
        self.assertEqual(result.shown[0], "ag_keith")
        self.assertEqual(set(result.scores), all_ids)


class IndexTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_stale_records_are_embedded(self) -> None:
        records = [view("ag_a", "Alpha"), view("ag_b", "Bravo"), view("ag_c", "Charlie")]
        index = EmbeddingIndex()
        embedder = FakeEmbedder()

        first = await select_candidates(records, "alpha", "user", [], RETRIEVE, embedder, index)
        self.assertEqual(first.embed_calls, 1)
        self.assertEqual(embedder.calls[0], ["alpha", "Alpha", "Bravo", "Charlie"])

        records[1] = view("ag_b", "Bravo", "new purpose")
        second = await select_candidates(records, "bravo", "user", [], RETRIEVE, embedder, index)
        self.assertEqual(second.embed_calls, 1)
        self.assertEqual(embedder.calls[1], ["bravo", "Bravo\nnew purpose"])

        third = await select_candidates(records, "charlie", "user", [], RETRIEVE, embedder, index)
        self.assertEqual(embedder.calls[2], ["charlie"])
        self.assertEqual(third.shown[0], "ag_c")

    async def test_model_or_dimension_change_makes_vectors_stale(self) -> None:
        index = EmbeddingIndex()
        index.put("ag_a", "Alpha", "m1", 2, [1.0, 1.0])
        self.assertFalse(index.is_stale("ag_a", "Alpha", "m1", 2))
        self.assertTrue(index.is_stale("ag_a", "Alpha", "m2", 2))
        self.assertTrue(index.is_stale("ag_a", "Alpha", "m1", 3))
        self.assertTrue(index.is_stale("ag_a", "Alpha!", "m1", 2))
        self.assertTrue(index.is_stale("ag_b", "Alpha", "m1", 2))

    async def test_large_stale_set_is_batched_at_64(self) -> None:
        records = filler(130)
        embedder = FakeEmbedder()
        result = await select_candidates(records, "filler", "user", [], RETRIEVE, embedder)
        self.assertEqual([len(c) for c in embedder.calls], [64, 64, 3])
        self.assertEqual(result.embed_calls, 3)

    def test_vectors_normalized_and_persisted_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "embeddings.json"
            index = EmbeddingIndex(path)
            index.put("ag_a", "Alpha", "m", 2, [3.0, 4.0])
            self.assertEqual(index.get("ag_a"), [0.6, 0.8])
            self.assertTrue(index.dirty)
            index.save()
            self.assertFalse(index.dirty)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["embeddings.json"])
            data = json.loads(path.read_text())
            self.assertEqual(data["vectors"]["ag_a"]["vector"], [0.6, 0.8])

            reloaded = EmbeddingIndex(path)
            self.assertFalse(reloaded.is_stale("ag_a", "Alpha", "m", 2))
            reloaded.clear()
            self.assertFalse(path.exists())

    def test_normalize_rounds_to_six_places(self) -> None:
        self.assertEqual(normalize([1.0, 2.0]), [0.447214, 0.894427])
        self.assertEqual(normalize([0.0, 0.0]), [0.0, 0.0])


class EmbedderFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_failure_falls_back_to_lexical(self) -> None:
        records = filler(10) + [view("ag_keith", "Email Keith", "Emails with Keith.")]
        result = await select_candidates(records, "reply to keith", "user", [], RETRIEVE, FakeEmbedder(fail=True))
        self.assertEqual(result.mode, "retrieved_lexical_fallback")
        self.assertIn("embedding service unavailable", result.error)
        self.assertEqual(result.embed_calls, 1)
        self.assertEqual(result.shown[0], "ag_keith")
        self.assertEqual(len(result.shown), RETRIEVE.k)   # bounded, not the full roster

    async def test_missing_embedder_falls_back(self) -> None:
        result = await select_candidates(filler(3), "x", "user", [], RETRIEVE, None)
        self.assertEqual(result.mode, "retrieved_lexical_fallback")

    async def test_semantic_off_is_not_a_failure(self) -> None:
        params = replace(RETRIEVE, use_semantic=False)
        result = await select_candidates(filler(3), "x", "user", [], params, None)
        self.assertEqual(result.mode, "retrieved")
        self.assertIsNone(result.error)


class ScorerTest(unittest.IsolatedAsyncioTestCase):
    async def test_pass_through_defers(self) -> None:
        records = filler(2)
        candidate_set = await select_candidates(records, "x", "user", [], RetrievalParams())
        decision = await InteractionAgentScorer().decide(
            ScoringInput("x", "user", (), tuple(records), candidate_set)
        )
        self.assertEqual(decision.kind, "defer")
        self.assertIsNone(decision.candidates)
        self.assertEqual((InteractionAgentScorer.name, InteractionAgentScorer.version), ("interaction_agent", "1"))


class OpenRouterEmbedderTest(unittest.IsolatedAsyncioTestCase):
    def _embedder(self, handler):
        embedder = OpenRouterEmbedder(
            "openai/text-embedding-3-small",
            2,
            api_key="test-key-not-real",
            transport=httpx.MockTransport(handler),
        )
        embedder.RETRY_DELAY_SECONDS = 0
        return embedder

    async def test_request_shape_and_ordering_by_index(self) -> None:
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]},
            )

        vectors = await self._embedder(handler).embed(["first", "second"], purpose="retrieval")
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        request = seen[0]
        self.assertEqual(str(request.url), "https://openrouter.ai/api/v1/embeddings")
        self.assertEqual(request.headers["authorization"], "Bearer test-key-not-real")
        self.assertEqual(
            json.loads(request.content),
            {
                "model": "openai/text-embedding-3-small",
                "input": ["first", "second"],
                "dimensions": 2,
                "encoding_format": "float",
                "provider": {"order": ["openai"], "allow_fallbacks": False},
            },
        )

    async def test_retries_on_429_and_5xx_then_succeeds(self) -> None:
        statuses = [429, 503]

        def handler(request: httpx.Request) -> httpx.Response:
            if statuses:
                return httpx.Response(statuses.pop(0), text="busy")
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

        self.assertEqual(await self._embedder(handler).embed(["x"], purpose="retrieval"), [[1.0, 0.0]])

    async def test_gives_up_after_two_retries(self) -> None:
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            raise httpx.ConnectError("offline")

        with self.assertRaises(EmbeddingError):
            await self._embedder(handler).embed(["x"], purpose="retrieval")
        self.assertEqual(len(attempts), 3)

    async def test_client_error_is_not_retried(self) -> None:
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(400, json={"error": "bad model"})

        with self.assertRaises(EmbeddingError):
            await self._embedder(handler).embed(["x"], purpose="retrieval")
        self.assertEqual(len(attempts), 1)

    async def test_wrong_dimensions_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]})

        with self.assertRaises(EmbeddingError):
            await self._embedder(handler).embed(["x"], purpose="retrieval")


if __name__ == "__main__":
    unittest.main()
