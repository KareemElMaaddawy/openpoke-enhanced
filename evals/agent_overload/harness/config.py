"""Load and validate a run config, apply a profile, and build the recorded config."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import HARNESS_VERSION
from .scoring import SCORER_VERSION
from .util import EVAL_ROOT, REPO_ROOT, canonical_json, sha256_file, sha256_hex, tree_hash

PROFILES = {
    "smoke": {"splits": ["dev"], "sizes": [10, 200], "reps": 1, "single_limit": 10, "sequence_limit": 1},
    "dev-quick": {"splits": ["dev"], "sizes": [10, 200], "reps": 1},
    "dev": {"splits": ["dev"]},
    "test": {"splits": ["test"]},
    "full": {"splits": ["dev", "test"]},
}
REQUIRED_KEYS = ("experiment", "harness_version", "scorer_version", "case_set", "method", "models", "suites", "runtime", "budget", "stats")
# Paths ignored by the dirty-tree check: run outputs and method caches, not code or fixtures.
DIRTY_IGNORE = ("evals/agent_overload/results/", "evals/agent_overload/cache/")
PLACEHOLDER_HASH = "<filled at freeze>"


class ConfigError(ValueError):
    pass


def load_config(path: Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise ConfigError(f"{path}: missing keys {missing}")
    if config["harness_version"] != HARNESS_VERSION:
        raise ConfigError(f"config harness_version {config['harness_version']} != harness {HARNESS_VERSION}")
    if str(config["scorer_version"]) != SCORER_VERSION:
        raise ConfigError(f"config scorer_version {config['scorer_version']} != scorer {SCORER_VERSION}")
    return config


@dataclass
class RunPlan:
    profile: str
    splits: list[str]
    single_sizes: dict[str, list[int]]
    sequence_sizes: dict[str, list[int]]
    single_reps: int
    sequence_reps: int
    modes: list[str]
    token_probe: bool
    single_limit: Optional[int] = None
    sequence_limit: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_plan(config: dict, profile: str) -> RunPlan:
    if profile not in PROFILES:
        raise ConfigError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    prof = PROFILES[profile]
    suites = config["suites"]
    single, sequence = suites["single"], suites["sequence"]
    splits = prof["splits"]
    sizes = prof.get("sizes")
    return RunPlan(
        profile=profile,
        splits=list(splits),
        single_sizes={s: list(sizes or single["roster_sizes"][s]) for s in splits},
        sequence_sizes={s: list(sizes or sequence["roster_sizes"][s]) for s in splits},
        single_reps=int(prof.get("reps", single["reps"])),
        sequence_reps=int(prof.get("reps", sequence["reps"])),
        modes=list(sequence["modes"]),
        token_probe=bool(suites.get("token_probe", {}).get("enabled", True)),
        single_limit=prof.get("single_limit"),
        sequence_limit=prof.get("sequence_limit"),
    )


def config_hash(config: dict, profile: str) -> str:
    """Hash of what defines the run's conditions: the config file and the profile.

    The cost cap (``--max-cost``) is left out: it decides when a run stops, not what it
    measures, so rerunning with a higher cap is the same configuration.
    """
    return sha256_hex(canonical_json({"config": config, "profile": profile}))


# ---------------------------------------------------------------------------
# Provenance


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def git_state() -> dict:
    try:
        sha = _git("rev-parse", "HEAD").strip()
        status = _git("status", "--porcelain")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"sha": None, "dirty": None, "dirty_paths": []}
    dirty = []
    for line in status.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path.startswith(DIRTY_IGNORE):
            dirty.append(path)
    return {"sha": sha, "dirty": bool(dirty), "dirty_paths": dirty[:50]}


def tracked_tree_hash(subdir: str) -> Optional[str]:
    """sha256 over tracked .py and .md files under ``subdir``."""
    try:
        listed = _git("ls-files", subdir).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    paths = [REPO_ROOT / p for p in listed if p.endswith((".py", ".md")) and (REPO_ROOT / p).exists()]
    return tree_hash(paths, REPO_ROOT)


def prompt_hashes() -> dict:
    from server.agents.interaction_agent.agent import SYSTEM_PROMPT  # noqa: F401
    from server.agents.interaction_agent.tools import TOOL_SCHEMAS
    from server.services.conversation.summarization import prompt_builder

    return {
        "interaction_system_prompt_sha256": sha256_file(
            REPO_ROOT / "server" / "agents" / "interaction_agent" / "system_prompt.md"
        ),
        "tool_schemas_sha256": sha256_hex(json.dumps(TOOL_SCHEMAS, sort_keys=True)),
        "summarizer_system_prompt_sha256": sha256_hex(prompt_builder._SYSTEM_PROMPT),
        "server_tree_sha256": tracked_tree_hash("server"),
        "harness_tree_sha256": tracked_tree_hash("evals/agent_overload/harness"),
    }


def build_recorded_config(
    *,
    config: dict,
    plan: RunPlan,
    run_id: str,
    cfg_hash: str,
    method_description: dict,
    fixtures_manifest: dict,
    fake: bool,
    max_cost_usd: float,
    observed_slugs: dict,
    accept_model_change: bool,
    started_at: str,
) -> dict:
    from server.agents.interaction_agent.runtime import InteractionAgentRuntime
    from server.config import get_settings

    settings = get_settings()
    return {
        "input_config": config,
        "run_id": run_id,
        "config_hash": cfg_hash,
        "fake_model": fake,
        "plan": plan.to_dict(),
        "git": git_state(),
        "harness_version": HARNESS_VERSION,
        "scorer_version": SCORER_VERSION,
        "case_set_version": fixtures_manifest.get("case_set_version"),
        "case_set_hash": fixtures_manifest.get("case_set_hash"),
        "hashes": prompt_hashes(),
        "method": method_description,
        "models": {
            "interaction": config["models"]["interaction"],
            "summarizer": config["models"]["summarizer"],
            "expected_canonical_slugs": config["models"]["expected_canonical_slugs"],
            "observed_canonical_slugs": observed_slugs,
            "accept_model_change": accept_model_change,
            "provider": config["models"]["provider"],
            "api": config["models"].get("api", "openrouter"),
            "openai_model_ids": config["models"].get("openai_model_ids"),
            "extra_params": config["models"].get("extra_params", {}),
        },
        "summarization": {
            "conversation_summary_threshold": settings.conversation_summary_threshold,
            "conversation_summary_tail_size": settings.conversation_summary_tail_size,
        },
        "max_tool_iterations": InteractionAgentRuntime.MAX_TOOL_ITERATIONS,
        "runtime": config["runtime"],
        "budget": {**config["budget"], "effective_max_cost_usd": max_cost_usd},
        "stats": config["stats"],
        "python_version": platform.python_version(),
        "started_at": started_at,
    }
