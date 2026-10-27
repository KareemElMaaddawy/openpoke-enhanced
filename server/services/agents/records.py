"""Agent records for records-mode routing: stable IDs, purpose, recent work."""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional

from ...logging_config import logger
from ...utils.timezones import now_in_user_timezone
from ..execution.log_store import _slugify

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..execution.log_store import ExecutionAgentLogStore
    from ..execution.roster import AgentRoster


INSTRUCTIONS_MAX_CHARS = 200
RESULT_MAX_CHARS = 150
PURPOSE_MAX_CHARS = 200
RECENT_WORK_MAX = 3

_STORE_VERSION = 1


def truncate_text(text: str, limit: int) -> str:
    """Collapse whitespace and cut to at most *limit* chars at a word boundary, ending with '…'."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


@dataclass
class WorkSnippet:
    instructions: str          # ≤ 200 chars, cut at a word boundary with "…"
    result: str                # ≤ 150 chars; "" until the agent finishes
    at: str                    # "YYYY-MM-DD HH:MM:SS", user timezone, time of dispatch


@dataclass
class AgentRecord:
    agent_id: str              # "ag_" + secrets.token_hex(4); never reused
    name: str                  # display name and the key for logs and triggers
    slug: str                  # log_store._slugify(name); unique across records
    purpose: str               # ≤ 200 chars; "" for imported agents
    recent_work: List[WorkSnippet]   # newest last, at most 3
    created_at: str            # "YYYY-MM-DD HH:MM:SS"
    last_active: str           # last delegation from the interaction agent
    task_count: int
    status: str = "active"     # only "active" in version 1; "archived" reserved for version 2
    aliases: List[str] = field(default_factory=list)   # legacy names that share this record's log
    purpose_source: str = "create"   # "create" | "import" | "backfill" | "instructions_fallback"

    @classmethod
    def from_dict(cls, data: dict) -> "AgentRecord":
        # Unknown keys (from a newer version, e.g. version 2's last_run) are ignored, not fatal.
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["recent_work"] = [WorkSnippet(**item) for item in data.get("recent_work", [])]
        return cls(**values)


class SlugCollision(Exception):
    """Raised when a new record's slug matches an existing record or alias."""

    def __init__(self, existing: AgentRecord):
        super().__init__(f"slug '{existing.slug}' already used by {existing.agent_id}")
        self.existing = existing


class AgentRecordStore:
    """Agent records persisted as {"version": 1, "records": [...]} in creation order."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._records: List[AgentRecord] = []
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """(Re)load records from disk. A missing file means no records; nothing is written."""
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        self._records = []
        self._loaded = True
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._records = [AgentRecord.from_dict(item) for item in data.get("records", [])]
        except Exception as exc:
            logger.warning(f"Failed to load {self._path.name}: {exc}")
            self._records = []

    def _ensure_loaded_locked(self) -> None:
        if not self._loaded:
            self._load_locked()

    def _save_locked(self) -> None:
        payload = {"version": _STORE_VERSION, "records": [asdict(r) for r in self._records]}
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, self._path)

    def _find_by_id_locked(self, agent_id: str) -> Optional[AgentRecord]:
        for record in self._records:
            if record.agent_id == agent_id:
                return record
        return None

    def _find_by_slug_locked(self, slug: str) -> Optional[AgentRecord]:
        for record in self._records:
            if record.slug == slug or any(_slugify(alias) == slug for alias in record.aliases):
                return record
        return None

    def _new_id_locked(self) -> str:
        while True:
            agent_id = "ag_" + secrets.token_hex(4)
            if self._find_by_id_locked(agent_id) is None:
                return agent_id

    def all(self, status: Optional[str] = "active") -> List[AgentRecord]:
        """Return copies of the records with *status* (all records when None), in creation order."""
        with self._lock:
            self._ensure_loaded_locked()
            return [
                copy.deepcopy(r) for r in self._records if status is None or r.status == status
            ]

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        with self._lock:
            self._ensure_loaded_locked()
            record = self._find_by_id_locked(agent_id)
            return copy.deepcopy(record) if record else None

    def find_by_name_or_slug(self, text: str) -> Optional[AgentRecord]:
        """Match an exact name, then an alias, then the slug."""
        candidate = str(text or "").strip()
        if not candidate:
            return None
        with self._lock:
            self._ensure_loaded_locked()
            for record in self._records:
                if record.name == candidate:
                    return copy.deepcopy(record)
            for record in self._records:
                if candidate in record.aliases:
                    return copy.deepcopy(record)
            record = self._find_by_slug_locked(_slugify(candidate))
            return copy.deepcopy(record) if record else None

    def create(
        self,
        name: str,
        purpose: str,
        now: str,
        *,
        purpose_source: str = "create",
    ) -> AgentRecord:
        """Create and persist a record. Raises SlugCollision if the slug is taken."""
        with self._lock:
            self._ensure_loaded_locked()
            record = AgentRecord(
                agent_id=self._new_id_locked(),
                name=name,
                slug=_slugify(name),
                purpose=truncate_text(purpose, PURPOSE_MAX_CHARS),
                recent_work=[],
                created_at=now,
                last_active=now,
                task_count=0,
                purpose_source=purpose_source,
            )
            self._insert_locked(record)
            return copy.deepcopy(record)

    def add_imported(self, record: AgentRecord) -> AgentRecord:
        """Insert a fully built record (used by the legacy import). Assigns a fresh agent_id."""
        with self._lock:
            self._ensure_loaded_locked()
            stored = copy.deepcopy(record)
            stored.agent_id = self._new_id_locked()
            stored.slug = _slugify(stored.name)
            self._insert_locked(stored)
            return copy.deepcopy(stored)

    def _insert_locked(self, record: AgentRecord) -> None:
        existing = self._find_by_slug_locked(record.slug)
        if existing is not None:
            raise SlugCollision(copy.deepcopy(existing))
        self._records.append(record)
        self._save_locked()

    def add_alias(self, agent_id: str, alias: str) -> None:
        with self._lock:
            self._ensure_loaded_locked()
            record = self._find_by_id_locked(agent_id)
            if record is None or alias == record.name or alias in record.aliases:
                return
            record.aliases.append(alias)
            self._save_locked()

    def touch_dispatch(self, agent_id: str, instructions: str, now: str) -> None:
        """Mark a delegation: last_active, task_count, and a new work snippet (keep the last 3)."""
        with self._lock:
            self._ensure_loaded_locked()
            record = self._find_by_id_locked(agent_id)
            if record is None:
                return
            record.last_active = now
            record.task_count += 1
            record.recent_work.append(
                WorkSnippet(
                    instructions=truncate_text(instructions, INSTRUCTIONS_MAX_CHARS),
                    result="",
                    at=now,
                )
            )
            del record.recent_work[:-RECENT_WORK_MAX]
            self._save_locked()

    def record_result(self, agent_id: str, result_text: str) -> None:
        """Fill the result of the newest snippet that has none."""
        result = truncate_text(result_text, RESULT_MAX_CHARS) or "(no response)"
        with self._lock:
            self._ensure_loaded_locked()
            record = self._find_by_id_locked(agent_id)
            if record is None:
                return
            for snippet in reversed(record.recent_work):
                if not snippet.result:
                    snippet.result = result
                    self._save_locked()
                    return

    def clear(self) -> None:
        with self._lock:
            self._records = []
            self._loaded = True
            try:
                if self._path.exists():
                    self._path.unlink()
                logger.info("Cleared agent records")
            except Exception as exc:
                logger.warning(f"Failed to clear {self._path.name}: {exc}")


# Import from the legacy roster

def _work_from_log(entries: Iterable[tuple[str, str, str]]) -> tuple[str, str, int, List[WorkSnippet]]:
    """Return (created_at, last_active, task_count, recent_work) from an execution log."""
    created_at = ""
    requests: List[WorkSnippet] = []
    pending: List[WorkSnippet] = []
    for tag, timestamp, payload in entries:
        if not created_at and timestamp:
            created_at = timestamp
        if tag == "agent_request":
            snippet = WorkSnippet(
                instructions=truncate_text(payload, INSTRUCTIONS_MAX_CHARS),
                result="",
                at=timestamp,
            )
            requests.append(snippet)
            pending.append(snippet)
        elif tag == "agent_response" and pending:
            # Pair each request with the next unpaired response; responses with no
            # open request (trigger runs) are skipped.
            pending.pop(0).result = truncate_text(payload, RESULT_MAX_CHARS) or "(no response)"
    last_active = requests[-1].at if requests else created_at
    return created_at, last_active, len(requests), requests[-RECENT_WORK_MAX:]


def reconcile_from_roster(
    store: AgentRecordStore,
    roster: "AgentRoster",
    log_store: "ExecutionAgentLogStore",
    now: Optional[str] = None,
) -> dict:
    """Give every roster name a record (or an alias on a slug-equal record). Returns counts."""
    if now is None:
        now = now_in_user_timezone("%Y-%m-%d %H:%M:%S")

    roster.load()
    created = aliased = 0
    for name in roster.get_agents():
        existing = store.find_by_name_or_slug(name)
        if existing is not None and (existing.name == name or name in existing.aliases):
            continue
        if existing is not None:
            store.add_alias(existing.agent_id, name)
            aliased += 1
            continue

        created_at, last_active, task_count, work = _work_from_log(log_store.iter_entries(name))
        store.add_imported(
            AgentRecord(
                agent_id="",
                name=name,
                slug=_slugify(name),
                purpose="",
                recent_work=work,
                created_at=created_at or now,
                last_active=last_active or now,
                task_count=task_count,
                purpose_source="import",
            )
        )
        created += 1

    counts = {"created": created, "aliased": aliased, "total": len(store.all())}
    logger.info(
        f"Agent records reconciled from roster: {created} imported, {aliased} aliased, "
        f"{counts['total']} active"
    )
    return counts


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_AGENTS_PATH = _DATA_DIR / "execution_agents" / "agents.json"

_agent_records = AgentRecordStore(_AGENTS_PATH)


def get_agent_records() -> AgentRecordStore:
    """Get the singleton record store. Nothing is read until first use."""
    return _agent_records


__all__ = [
    "AgentRecord",
    "AgentRecordStore",
    "SlugCollision",
    "WorkSnippet",
    "get_agent_records",
    "reconcile_from_roster",
    "truncate_text",
]
