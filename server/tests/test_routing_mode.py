"""The legacy/records switch: settings, the --routing flag, meta, startup log and reset."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.agents.interaction_agent import routing as routing_module
from server.agents.interaction_agent.routing import (
    LegacyRouting,
    RecordsRouting,
    describe_routing,
    get_routing_strategy,
    initialize_routing,
)
from server.config import Settings, get_settings
from server.services.agents.records import AgentRecordStore
from server.services.routing.embeddings import EmbeddingIndex
from server.services.routing.params import RetrievalParams
from server.tests.runtime_helpers import TempServerState, make_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTING_ENV = ("OPENPOKE_ROUTING", "OPENPOKE_FULL_ROSTER_MAX")


def _clean_env(**values: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ROUTING_ENV}
    env.update(values)
    return env


class RoutingModeSettingTest(unittest.TestCase):
    def test_unset_gives_legacy(self) -> None:
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(Settings().routing_mode, "legacy")

    def test_records(self) -> None:
        with mock.patch.dict(os.environ, _clean_env(OPENPOKE_ROUTING="records"), clear=True):
            self.assertEqual(Settings().routing_mode, "records")
        with mock.patch.dict(os.environ, _clean_env(OPENPOKE_ROUTING=" Records "), clear=True):
            self.assertEqual(Settings().routing_mode, "records")

    def test_bad_value_raises(self) -> None:
        with mock.patch.dict(os.environ, _clean_env(OPENPOKE_ROUTING="fancy"), clear=True):
            with self.assertRaisesRegex(ValueError, "OPENPOKE_ROUTING must be one of: legacy, records"):
                Settings()

    def test_env_is_read_when_settings_are_built(self) -> None:
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            first = Settings()
            os.environ["OPENPOKE_ROUTING"] = "records"
            self.assertEqual((first.routing_mode, Settings().routing_mode), ("legacy", "records"))

    def test_strategy_follows_setting(self) -> None:
        state = TempServerState(make_settings(routing_mode="legacy")).start()
        self.addCleanup(state.stop)
        self.assertIsInstance(get_routing_strategy(), LegacyRouting)
        state.settings = make_settings(routing_mode="records")
        strategy = get_routing_strategy()
        self.assertIsInstance(strategy, RecordsRouting)
        self.assertEqual([s["function"]["name"] for s in strategy.tool_schemas()][:2], ["send_message_to_agent", "create_agent"])
        self.assertIn("create_agent", strategy.build_system_prompt())


class FullRosterMaxSettingTest(unittest.TestCase):
    def _settings(self, value=None) -> Settings:
        env = _clean_env() if value is None else _clean_env(OPENPOKE_FULL_ROSTER_MAX=value)
        with mock.patch.dict(os.environ, env, clear=True):
            return Settings()

    def test_unset_gives_default_25(self) -> None:
        self.assertEqual(RetrievalParams().full_roster_max, 25)
        self.assertEqual(self._settings().full_roster_max, 25)
        self.assertEqual(self._settings("").full_roster_max, 25)

    def test_valid_values_are_used(self) -> None:
        self.assertEqual(self._settings("3").full_roster_max, 3)
        self.assertEqual(self._settings(" 40 ").full_roster_max, 40)
        self.assertEqual(self._settings("0").full_roster_max, 0)

    def test_negative_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENPOKE_FULL_ROSTER_MAX must be an integer >= 0"):
            self._settings("-1")

    def test_non_integer_raises(self) -> None:
        for bad in ("abc", "3.5", "1e3"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, "OPENPOKE_FULL_ROSTER_MAX must be an integer >= 0"):
                    self._settings(bad)
        with self.assertRaises(ValueError):
            Settings(full_roster_max=-5)

    def test_records_routing_uses_the_setting(self) -> None:
        state = TempServerState(make_settings(routing_mode="records", full_roster_max=3)).start()
        self.addCleanup(state.stop)
        strategy = get_routing_strategy()
        self.assertEqual(strategy.params.full_roster_max, 3)
        self.assertEqual(strategy.params.k, RetrievalParams().k)

    def test_startup_line_shows_mode_and_full_roster_max(self) -> None:
        self.assertEqual(
            describe_routing(make_settings(routing_mode="records", full_roster_max=3)),
            "Routing mode: records (embeddings openai/text-embedding-3-small@512, K=8, full_roster_max=3)",
        )
        self.assertEqual(describe_routing(make_settings(routing_mode="legacy")), "Routing mode: legacy")


class InitializeRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TempServerState(make_settings(routing_mode="records", full_roster_max=3)).start()
        self.addCleanup(self.state.stop)
        self.state.roster.add_agent("Email Keith")
        self.state.roster.add_agent("email-keith")

    def test_records_logs_and_imports_roster(self) -> None:
        with self.assertLogs("openpoke.server", "INFO") as logs:
            initialize_routing()
        self.assertIn(
            "Routing mode: records (embeddings openai/text-embedding-3-small@512, K=8, full_roster_max=3)",
            "\n".join(logs.output),
        )
        records = self.state.records.all()
        self.assertEqual([(r.name, r.aliases) for r in records], [("Email Keith", ["email-keith"])])

    def test_legacy_logs_and_imports_nothing(self) -> None:
        self.state.settings = make_settings(routing_mode="legacy")
        with self.assertLogs("openpoke.server", "INFO") as logs:
            initialize_routing()
        self.assertEqual([r.getMessage() for r in logs.records], ["Routing mode: legacy"])
        self.assertFalse((self.state.base / "execution_agents" / "agents.json").exists())


class AppStartupHookTest(unittest.TestCase):
    def test_app_startup_logs_routing_mode(self) -> None:
        import importlib

        app_module = importlib.import_module("server.app")  # the module; `server.app` is the FastAPI object

        state = TempServerState(make_settings(routing_mode="records", full_roster_max=3)).start()
        self.addCleanup(state.stop)
        state.roster.add_agent("Legacy Agent")
        background = mock.Mock(start=mock.AsyncMock(), stop=mock.AsyncMock())
        with mock.patch.object(app_module, "get_trigger_scheduler", return_value=background), \
                mock.patch.object(app_module, "get_important_email_watcher", return_value=background), \
                self.assertLogs("openpoke.server", "INFO") as logs:
            with TestClient(app_module.app):   # runs the startup and shutdown hooks
                pass
        self.assertIn("full_roster_max=3)", "\n".join(logs.output))
        self.assertEqual([r.name for r in state.records.all()], ["Legacy Agent"])


class MetaTest(unittest.TestCase):
    def test_meta_reports_routing_mode(self) -> None:
        from server.app import app

        client = TestClient(app)  # no `with`: startup hooks (scheduler, watcher) don't run
        for mode in ("legacy", "records"):
            app.dependency_overrides[get_settings] = lambda mode=mode: make_settings(routing_mode=mode)
            try:
                body = client.get("/api/v1/meta").json()
            finally:
                app.dependency_overrides.clear()
            self.assertEqual(body["routing_mode"], mode)


class ResetTest(unittest.TestCase):
    def test_reset_deletes_records_and_embeddings(self) -> None:
        from server.routes import chat as chat_routes

        with tempfile.TemporaryDirectory() as tmp:
            store = AgentRecordStore(Path(tmp) / "agents.json")
            store.create("Worker", "", "2026-10-26 10:00:00")
            index = EmbeddingIndex(Path(tmp) / "embeddings.json")
            index.put("ag_x", "Worker", "m", 2, [1.0, 0.0])
            index.save()

            others = {name: mock.Mock() for name in ("conversation", "logs", "roster", "triggers")}
            with mock.patch.object(chat_routes, "get_conversation_log", return_value=others["conversation"]), \
                    mock.patch.object(chat_routes, "get_trigger_service", return_value=others["triggers"]), \
                    mock.patch("server.services.get_execution_agent_logs", return_value=others["logs"]), \
                    mock.patch("server.services.get_agent_roster", return_value=others["roster"]), \
                    mock.patch("server.services.agents.get_agent_records", return_value=store), \
                    mock.patch.object(routing_module, "get_embedding_index", return_value=index):
                chat_routes.clear_history()

            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])
            self.assertEqual(store.all(), [])
            others["conversation"].clear.assert_called_once()
            others["logs"].clear_all.assert_called_once()
            others["roster"].clear.assert_called_once()
            others["triggers"].clear_all.assert_called_once()


class ServerFlagTest(unittest.TestCase):
    """`server.server --routing records` sets the environment before the app reads settings,
    checked in a subprocess with uvicorn.run patched (nothing is served, no network)."""

    SCRIPT = textwrap.dedent(
        """
        import json, os, sys
        from unittest import mock
        import uvicorn

        captured = {}

        def fake_run(app, **kwargs):
            from fastapi.testclient import TestClient
            from server.app import app as app_object
            from server.config import get_settings
            captured["env"] = os.environ.get("OPENPOKE_ROUTING")
            captured["settings"] = get_settings().routing_mode
            captured["meta"] = TestClient(app_object).get("/api/v1/meta").json()["routing_mode"]
            captured["app"] = app if isinstance(app, str) else "object"
            captured["reload"] = kwargs.get("reload")

        with mock.patch.object(uvicorn, "run", fake_run):
            sys.argv = ["server.server"] + sys.argv[1:]
            from server import server as cli
            cli.main()
        print("RESULT " + json.dumps(captured))
        """
    )

    def _run(self, *args: str, **env: str) -> dict:
        proc = subprocess.run(
            [sys.executable, "-c", self.SCRIPT, *args],
            cwd=REPO_ROOT,
            env=_clean_env(**env),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT ")][-1]
        return json.loads(line[len("RESULT "):])

    def test_routing_flag(self) -> None:
        self.assertEqual(
            self._run("--routing", "records"),
            {"env": "records", "settings": "records", "meta": "records", "app": "object", "reload": False},
        )

    def test_routing_flag_with_reload_reaches_the_worker_environment(self) -> None:
        result = self._run("--routing", "records", "--reload")
        self.assertEqual((result["env"], result["app"], result["reload"]), ("records", "server.app:app", True))

    def test_flag_overrides_environment(self) -> None:
        result = self._run("--routing", "legacy", OPENPOKE_ROUTING="records")
        self.assertEqual((result["env"], result["meta"]), ("legacy", "legacy"))

    def test_default_is_legacy(self) -> None:
        result = self._run()
        self.assertEqual((result["env"], result["settings"], result["meta"]), (None, "legacy", "legacy"))


if __name__ == "__main__":
    unittest.main()
