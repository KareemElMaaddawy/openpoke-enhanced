"""names_only parity with production (prompt, stubs, payload) and loop behaviour."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server.openrouter_client.client as openrouter_client
import server.services.conversation.log as conversation_log_module
import server.services.conversation.summarization as summarization_package
from server.agents.interaction_agent import agent as agent_module
from server.agents.interaction_agent import tools as real_tools
from server.agents.interaction_agent.agent import build_system_prompt, prepare_message_with_history
from server.agents.interaction_agent.tools import TOOL_SCHEMAS
from server.services.conversation.log import ConversationLog
from server.services.conversation.summarization.working_memory_log import WorkingMemoryLog
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import AgentRoster

from evals.agent_overload.harness import llm
from evals.agent_overload.harness.methods import names_only
from evals.agent_overload.harness.methods.base import AgentView, Entry, RoutingInput
from evals.agent_overload.harness.state import render_transcript

NAMES = ["AWS Invoice Lookup", 'Re: "Keith" <offsite> & plans', "Gym Reminder"]
ENTRIES = (
    Entry("user_message", "2026-10-20 09:14:00", "find my AWS invoice"),
    Entry("poke_reply", "2026-10-20 09:14:05", "on it"),
    Entry("agent_message", "2026-10-20 09:15:10", "[SUCCESS] AWS Invoice Lookup: Found it: $412.37"),
)


def make_input(names=NAMES, text="forward that to my accountant", message_type="user", entries=ENTRIES, summary=""):
    roster = tuple(AgentView(f"a-{i}", n, (), "2026-10-01 08:00:00", "2026-10-20 09:15:10") for i, n in enumerate(names))
    return RoutingInput(roster=roster, summary_text=summary, entries=entries, message_text=text, message_type=message_type)


class PromptParityTest(unittest.TestCase):
    def check(self, inp: RoutingInput):
        system, messages = names_only.build_messages(inp)
        with tempfile.TemporaryDirectory() as tmp:
            roster = AgentRoster(Path(tmp) / "roster.json")
            for agent in inp.roster:
                roster.add_agent(agent.name)
            with mock.patch.object(agent_module, "get_agent_roster", lambda: roster):
                transcript = render_transcript(inp.summary_text, inp.entries)
                expected = prepare_message_with_history(inp.message_text, transcript, message_type=inp.message_type)
        self.assertEqual(system, build_system_prompt())
        self.assertEqual(messages, expected)
        return messages

    def test_user_message_with_roster(self):
        messages = self.check(make_input())
        self.assertIn('<agent name="Re: &quot;Keith&quot; &lt;offsite&gt; &amp; plans" />', messages[0]["content"])

    def test_agent_message_empty_roster_and_history(self):
        messages = self.check(make_input(names=[], entries=(), text="Important email watcher notification:\nhi", message_type="agent"))
        self.assertIn("<active_agents>\nNone\n</active_agents>", messages[0]["content"])
        self.assertIn("<conversation_history>\nNone\n</conversation_history>", messages[0]["content"])

    def test_with_summary(self):
        self.check(make_input(summary="Summary generated: 2026-10-20\n- stuff"))

    def test_contextvar_roster_does_not_leak_between_concurrent_turns(self):
        async def build(names):
            await asyncio.sleep(0)
            return names_only.build_messages(make_input(names=names))[1][0]["content"]

        async def both():
            return await asyncio.gather(build(["Alpha"]), build(["Beta", "Gamma"]))

        first, second = asyncio.run(both())
        self.assertIn("Alpha", first)
        self.assertNotIn("Beta", first)
        self.assertIn("Gamma", second)


class StubParityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.wml = WorkingMemoryLog(root / "wm.log")
        patches = [
            mock.patch.object(conversation_log_module, "_resolve_working_memory_log", lambda: self.wml),
            mock.patch.object(summarization_package, "schedule_summarization", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.conversation = ConversationLog(root / "conversation.log")
        self.roster = AgentRoster(root / "roster.json")
        self.roster.add_agent("AWS Invoice Lookup")
        self.logs = ExecutionAgentLogStore(root / "logs")
        for target, value in (
            ("get_conversation_log", lambda: self.conversation),
            ("get_agent_roster", lambda: self.roster),
            ("get_execution_agent_logs", lambda: self.logs),
        ):
            p = mock.patch.object(real_tools, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(real_tools._EXECUTION_BATCH_MANAGER, "execute_agent", mock.AsyncMock())
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def stubs(self, roster_names=("AWS Invoice Lookup",)):
        recorder = names_only.TurnRecorder(tuple(AgentView(f"a-{i}", n, (), "", "") for i, n in enumerate(roster_names)))
        return names_only.ToolStubs(recorder), recorder

    @staticmethod
    def fields(result):
        return (result.success, result.payload, result.user_message, result.recorded_reply)

    def real(self, name, args):
        async def call():
            return real_tools.handle_tool_call(name, args)

        return asyncio.run(call())

    def test_send_message_to_agent_new_then_existing(self):
        stubs, recorder = self.stubs()
        for args in (
            {"agent_name": "Denver Flights", "instructions": "find flights"},
            {"agent_name": "Denver Flights", "instructions": "again"},
            {"agent_name": "AWS Invoice Lookup", "instructions": "forward it"},
        ):
            self.assertEqual(self.fields(stubs.handle_tool_call("send_message_to_agent", args)), self.fields(self.real("send_message_to_agent", args)))
        self.assertEqual([d.agent_key for d in recorder.delegations], ["new:Denver Flights", "new:Denver Flights", "a-0"])

    def test_send_message_to_user(self):
        stubs, recorder = self.stubs()
        args = {"message": "on it"}
        self.assertEqual(self.fields(stubs.handle_tool_call("send_message_to_user", args)), self.fields(self.real("send_message_to_user", args)))
        self.assertEqual(recorder.effects, [Entry("poke_reply", "", "on it")])

    def test_send_draft(self):
        stubs, recorder = self.stubs()
        args = {"to": "a@b.com", "subject": "Hi", "body": "Body\nline"}
        self.assertEqual(self.fields(stubs.handle_tool_call("send_draft", args)), self.fields(self.real("send_draft", args)))
        self.assertEqual(recorder.effects[0].payload, "To: a@b.com\nSubject: Hi\n\nBody\nline")
        self.assertEqual(self.conversation.load_transcript().count("To: a@b.com"), 1)

    def test_wait(self):
        stubs, recorder = self.stubs()
        args = {"reason": "dup"}
        self.assertEqual(self.fields(stubs.handle_tool_call("wait", args)), self.fields(self.real("wait", args)))
        self.assertEqual(recorder.effects, [Entry("wait", "", "dup")])

    def test_error_paths_match(self):
        stubs, _ = self.stubs()
        for name, args in (
            ("send_message_to_agent", {"agent_name": "X"}),
            ("send_message_to_agent", {"agent_name": "X", "instructions": "y", "extra": 1}),
            ("send_message_to_user", {}),
            ("nope", {}),
            ("wait", "{not json"),
            ("wait", 42),
            ("send_message_to_agent", {"agent_name": ["x"], "instructions": "y"}),
        ):
            self.assertEqual(self.fields(stubs.handle_tool_call(name, args)), self.fields(self.real(name, args)), (name, args))

    def test_empty_name_answers_like_production_but_records_invalid(self):
        stubs, recorder = self.stubs()
        args = {"agent_name": "", "instructions": "y"}
        self.assertEqual(self.fields(stubs.handle_tool_call("send_message_to_agent", args)), self.fields(self.real("send_message_to_agent", args)))
        self.assertEqual(recorder.delegations, [])
        self.assertEqual(recorder.invalid_calls[0]["error"], "empty agent_name")


class PayloadParityTest(unittest.TestCase):
    def test_payload_matches_request_chat_completion(self):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": []}

        async def fake_post(self, url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return FakeResponse()

        system, messages = names_only.build_messages(make_input())
        with mock.patch.object(openrouter_client.httpx.AsyncClient, "post", fake_post):
            asyncio.run(
                openrouter_client.request_chat_completion(
                    model="openai/gpt-6-luna", messages=messages, system=system, api_key="test-key", tools=TOOL_SCHEMAS
                )
            )
        ours = llm.build_payload(
            model="openai/gpt-6-luna",
            messages=messages,
            system=system,
            tools=TOOL_SCHEMAS,
            provider={"order": ["openai"], "allow_fallbacks": False},
            seed=123456789,
        )
        self.assertEqual(llm.production_view(ours), captured["json"])
        self.assertEqual(ours["provider"], {"order": ["openai"], "allow_fallbacks": False})
        self.assertEqual(ours["usage"], {"include": True})
        self.assertEqual(ours["seed"], 123456789)

    def test_summarizer_payload_has_no_tools(self):
        payload = llm.build_payload(model="m", messages=[{"role": "user", "content": "x"}], system="s")
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "s"})


def scripted(*steps):
    """Responder that plays ``steps`` in order (one per call), repeating the last."""
    state = {"i": 0, "payloads": []}

    def responder(payload, hint):
        state["payloads"].append(payload)
        step = steps[min(state["i"], len(steps) - 1)]
        state["i"] += 1
        return step

    return responder, state


def call(name, args, cid="call_0"):
    return llm.fake_tool_call(cid, name, args)


class LoopBehaviourTest(unittest.TestCase):
    def route(self, responder, inp=None):
        client = llm.FakeClient(responders={"routing": responder})
        method = names_only.NamesOnlyMethod(client, model="openai/gpt-6-luna", provider={"order": ["openai"]})
        llm.CALL_CONTEXT.set({"case_id": "s-test-0001", "N": 10, "mode": None, "rep": 0, "turn": None})
        return asyncio.run(method.route(inp or make_input()))

    def test_reply_then_delegate_then_finish(self):
        responder, state = scripted(
            llm.fake_message("", [call("send_message_to_user", {"message": "on it"}), call("send_message_to_agent", {"agent_name": "AWS Invoice Lookup", "instructions": "forward"}, "call_1")]),
            llm.fake_message(""),
        )
        out = self.route(responder)
        self.assertEqual([(d.agent_key, d.iteration) for d in out.delegations], [("a-0", 0)])
        self.assertEqual(out.history_effects, [Entry("poke_reply", "", "on it")])
        self.assertEqual(len(out.llm_calls), 2)
        self.assertNotEqual(out.llm_calls[0].seed, out.llm_calls[1].seed)
        tool_messages = [m for m in state["payloads"][1]["messages"] if m["role"] == "tool"]
        self.assertEqual(json.loads(tool_messages[1]["content"])["result"]["new_agent_created"], False)
        self.assertFalse(out.loop_limit_hit)

    def test_same_new_name_twice_reuses_key(self):
        responder, state = scripted(
            llm.fake_message("", [call("send_message_to_agent", {"agent_name": "Denver", "instructions": "a"}), call("send_message_to_agent", {"agent_name": "Denver", "instructions": "b"}, "call_1")]),
            llm.fake_message("done"),
        )
        out = self.route(responder)
        self.assertEqual([d.agent_key for d in out.delegations], ["new:Denver", "new:Denver"])
        results = [json.loads(m["content"])["result"] for m in state["payloads"][1]["messages"] if m["role"] == "tool"]
        self.assertEqual([r["new_agent_created"] for r in results], [True, False])
        self.assertEqual(out.history_effects, [Entry("poke_reply", "", "done")])  # assistant text, no send_message_to_user

    def test_invalid_calls(self):
        responder, _ = scripted(
            llm.fake_message(
                "",
                [
                    call("send_message_to_agent", {"agent_name": "", "instructions": "a"}, "c1"),
                    call("send_message_to_agent", {"agent_name": "X"}, "c2"),
                    call("send_message_to_agent", '{"agent_name": "br', "c3"),
                    call("make_coffee", {}, "c4"),
                    {"id": "c5", "type": "function", "function": {"name": "", "arguments": "{}"}},
                ],
            ),
            llm.fake_message(""),
        )
        out = self.route(responder)
        self.assertEqual(out.delegations, [])
        errors = [c["error"] for c in out.invalid_calls]
        self.assertEqual(errors[0], "tool call without name")
        self.assertIn("empty agent_name", errors)
        self.assertTrue(any(e.startswith("Missing required arguments") for e in errors))
        self.assertTrue(any(e.startswith("invalid json") for e in errors))
        self.assertIn("Unknown tool: make_coffee", errors)
        self.assertTrue(any(c["raw_arguments"] == '{"agent_name": "br' for c in out.invalid_calls))

    def test_stop_at_first_delegation(self):
        responder, _ = scripted(
            llm.fake_message("", [call("send_message_to_agent", {"agent_name": "", "instructions": "a"}, "c1")]),
            llm.fake_message("", [call("send_message_to_agent", {"agent_name": "Denver", "instructions": "b"}, "c2"), call("send_message_to_agent", {"agent_name": "Later", "instructions": "c"}, "c3")]),
            llm.fake_message("done"),
        )
        client = llm.FakeClient(responders={"routing": responder})
        method = names_only.NamesOnlyMethod(client, model="openai/gpt-6-luna", stop_at_first_delegation=True)
        llm.CALL_CONTEXT.set({"case_id": "t-dev-0001", "N": 0, "mode": None, "rep": 1, "turn": None})
        out = asyncio.run(method.route(make_input()))
        self.assertEqual([d.agent_name for d in out.delegations], ["Denver"])  # the empty name doesn't count
        self.assertEqual(len(out.llm_calls), 2)
        self.assertFalse(out.loop_limit_hit)

    def test_wait_only_response_ends_the_turn(self):
        responder, _ = scripted(
            llm.fake_message("", [call("send_message_to_agent", {"agent_name": "AWS Invoice Lookup", "instructions": "x"})]),
            llm.fake_message("", [call("wait", {"reason": "agent is working"}, "c1")]),
            llm.fake_message("", [call("send_message_to_agent", {"agent_name": "Never", "instructions": "y"}, "c2")]),
        )
        out = self.route(responder)
        self.assertEqual(len(out.llm_calls), 2)
        self.assertEqual([d.agent_name for d in out.delegations], ["AWS Invoice Lookup"])
        self.assertEqual(out.history_effects, [Entry("wait", "", "agent is working")])
        self.assertFalse(out.loop_limit_hit)

    def test_wait_with_other_calls_continues(self):
        responder, _ = scripted(
            llm.fake_message("", [call("wait", {"reason": "dup"}), call("send_message_to_user", {"message": "hi"}, "c1")]),
            llm.fake_message("done"),
        )
        out = self.route(responder)
        self.assertEqual(len(out.llm_calls), 2)

    def test_loop_limit_keeps_delegations(self):
        responder, _ = scripted(llm.fake_message("", [call("send_message_to_agent", {"agent_name": "Loop", "instructions": "x"})]))
        out = self.route(responder)
        self.assertTrue(out.loop_limit_hit)
        self.assertEqual(len(out.llm_calls), 8)
        self.assertEqual(len(out.delegations), 8)
        self.assertEqual({d.iteration for d in out.delegations}, set(range(8)))

    def test_seeds_are_deterministic_per_position(self):
        responder, _ = scripted(llm.fake_message(""))
        a = self.route(responder).llm_calls[0].seed
        responder, _ = scripted(llm.fake_message(""))
        b = self.route(responder).llm_calls[0].seed
        self.assertEqual(a, b)

    def test_missing_assistant_message_is_api_error(self):
        client = llm.FakeClient(responders={"routing": lambda p, h: None})
        method = names_only.NamesOnlyMethod(client, model="openai/gpt-6-luna")
        with self.assertRaises(llm.ApiError):
            asyncio.run(method.route(make_input()))


if __name__ == "__main__":
    unittest.main()
