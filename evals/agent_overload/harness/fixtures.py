"""Load a frozen fixture set and verify it against its MANIFEST.

Every file under the version directory except ``MANIFEST.json`` is hashed. Loading
fails if any listed file is missing or changed, or if an unlisted file appears.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .util import read_jsonl, sha256_file, sha256_hex

SPLITS = ("dev", "test")
MANIFEST_NAME = "MANIFEST.json"


class FixtureError(RuntimeError):
    pass


def fixture_files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.name != MANIFEST_NAME and p.name != ".DS_Store"),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def file_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in fixture_files(root)}


def case_set_hash(hashes: dict[str, str]) -> str:
    """``sha256("".join(f"{path}\\0{sha256(file)}\\n" for path in sorted(fixture_files)))``."""
    return sha256_hex("".join(f"{path}\0{hashes[path]}\n" for path in sorted(hashes)))


@dataclass
class FixtureSet:
    root: Path
    manifest: dict
    threads: dict[str, dict[str, dict]] = field(default_factory=dict)
    agents: dict[str, dict[str, dict]] = field(default_factory=dict)
    agent_of_thread: dict[str, dict[str, str]] = field(default_factory=dict)
    rosters: dict[str, dict] = field(default_factory=dict)
    single: dict[str, list[dict]] = field(default_factory=dict)
    sequences: dict[str, list[dict]] = field(default_factory=dict)
    chitchat: list[dict] = field(default_factory=list)

    @property
    def case_set_hash(self) -> str:
        return self.manifest["case_set_hash"]


def verify_manifest(root: Path, manifest: dict) -> None:
    listed = manifest.get("files") or {}
    actual = file_hashes(root)
    problems = []
    for path, digest in listed.items():
        if path not in actual:
            problems.append(f"missing: {path}")
        elif actual[path] != digest:
            problems.append(f"changed: {path}")
    for path in actual:
        if path not in listed:
            problems.append(f"not in manifest: {path}")
    if problems:
        raise FixtureError("fixture set does not match MANIFEST.json:\n  " + "\n  ".join(problems[:20]))
    if case_set_hash(listed) != manifest.get("case_set_hash"):
        raise FixtureError("MANIFEST.json case_set_hash does not match its file hashes")


def load_fixtures(manifest_path: Path, expected_hash: Optional[str] = None, verify: bool = True) -> FixtureSet:
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FixtureError(f"{manifest_path} not found: fixtures are not frozen yet (run generation/freeze.py)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    if verify:
        verify_manifest(root, manifest)
    if expected_hash is not None and manifest["case_set_hash"] != expected_hash:
        raise FixtureError(
            f"case_set_hash {manifest['case_set_hash']} != config expected_hash {expected_hash}"
        )
    return read_fixture_dir(root, manifest)


def read_fixture_dir(root: Path, manifest: Optional[dict] = None) -> FixtureSet:
    """Read the data files without verification (used by freeze.py and generation)."""
    fs = FixtureSet(root=root, manifest=manifest or {})
    for split in SPLITS:
        threads_path = root / f"threads.{split}.jsonl"
        if not threads_path.exists():
            continue
        fs.threads[split] = {t["thread_id"]: t for t in read_jsonl(threads_path)}
        agents_path = root / f"agents.{split}.jsonl"
        fs.agents[split] = {a["agent_id"]: a for a in read_jsonl(agents_path)} if agents_path.exists() else {}
        fs.agent_of_thread[split] = {a["thread_id"]: a["agent_id"] for a in fs.agents[split].values()}
        rosters_path = root / f"rosters.{split}.json"
        if rosters_path.exists():
            fs.rosters[split] = json.loads(rosters_path.read_text(encoding="utf-8"))
        single_path = root / f"cases.single.{split}.jsonl"
        fs.single[split] = read_jsonl(single_path) if single_path.exists() else []
        seq_path = root / f"cases.sequence.{split}.jsonl"
        fs.sequences[split] = read_jsonl(seq_path) if seq_path.exists() else []
    chitchat = root / "chitchat.jsonl"
    fs.chitchat = read_jsonl(chitchat) if chitchat.exists() else []
    return fs
