# Agent overload: richer records and bounded retrieval (spec)

The implementation spec for the first solution version: richer agent records, routing by agent ID, and bounded retrieval of candidate agents, with a slot for a scorer that later work fills in. It's written so an implementing agent can build it without making design decisions. Decisions still open are listed as such, with the rule for settling them.

The problem, the candidate directions and the decision log are in [agent-overload.md](agent-overload.md). Causes (D1, I2, ...) and metrics are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md). The harness this plugs into is in [agent-overload-experiment-design.md](agent-overload-experiment-design.md).

Status: designed 2026-10-26. Steps 1 to 4 of the [implementation order](#implementation-order) (server side) implemented 2026-10-26. Steps 6 (harness) and 7 (runbook section) implemented 2026-10-27, after the phase 1 baseline (`20261027-035635-names_only-e5cf9a5a`) had run. Step 5 was tried once by hand; the experiment plan's paid steps 2 to 7 haven't run. Decisions made while implementing are in [Implementation notes](#implementation-notes).

## Where this stands in the method

- **Problem and metrics:** agreed (2026-10-25).
- **Baseline:** designed, being built in a separate branch, **not yet measured**. So none of the hypotheses below has evidence yet, and the numeric parameters (K, the full-roster threshold, fusion weights) can't be chosen yet. This spec makes them config values with a dev-only tuning rule, instead of guessing.
- **This spec** covers the hypotheses, the design and the experiments for version 1. Archiving and the history cap (version 2) are out of scope, but the record schema leaves room for them.

## Scope

In scope:

1. **Agent records** with a stable ID, name, purpose, recent work, timestamps and status. Stored next to the existing roster and kept in sync with it.
2. **ID routing.** Reuse is by `agent_id`. Creating an agent is a separate tool that needs a purpose and refuses names that collide.
3. **Bounded retrieval.** Above a roster size threshold, the interaction agent sees at most K candidate records. They're chosen by pinned agents from recent context, embedding similarity, lexical (BM25) similarity, and an optional recency prior.
4. **A scorer slot.** An interface between retrieval and the prompt. Version 1 ships only the pass-through scorer: the interaction agent decides among the candidates, which is the control in [Scorer options](agent-overload.md#scorer-options).
5. **A startup switch** between the current system (`legacy`) and this one (`records`).
6. **Harness integration:** a routing method `records_retrieval` for the eval harness, and a cheap retrieval-only probe for tuning.

Out of scope: archiving, the execution history cap, scorers other than the pass-through one, changes to execution agents (their system prompt still says `Handle tasks related to: {name}`), and parallel-split specific behaviour.

## Hypotheses this version tests

Each comes with what would reject it. All of them are measured on dev first and on test once.

| ID | Hypothesis | Causes | Evidence that would reject it |
| --- | --- | --- | --- |
| H1 | Records plus ID routing, with the **full** roster, improve routing accuracy over names only. The gain is largest on `paraphrased` and `near_distractor` queries and on `generic` names, and the `near_duplicate` share of false spawns falls. | I2, I3, I4 | `records_full` accuracy is not above `names_only` at matched N, or the gain is only within CI noise in every query style |
| H2 | Retrieval keeps accuracy close to `records_full` while roster tokens per turn stop growing with N | I1, D1 | Accuracy at N = 200 drops well below `records_full`, with most errors tagged `target_excluded` |
| H3 | Pinning agents named in recent results is what makes implicit follow-ups ("reply to that") work under retrieval | I1 | Recall@K on `implicit_follow_up` is about the same with and without pins |
| H4 | A written purpose adds routing signal beyond name plus recent work | I2 | Dev accuracy with `seed_purposes: "none"` is no worse than with `"backfill"` |

Targets (how much better counts as success) are set after the baseline, as agreed, and written into [agent-overload.md](agent-overload.md#decisions) **before** the test run.

## Decisions taken in this spec (to confirm)

These were choices, not facts. Each is a recommendation the user can overturn before implementation starts.

| # | Decision | Recommendation | Main alternative and why not |
| --- | --- | --- | --- |
| 1 | Mode switch | `OPENPOKE_ROUTING=legacy\|records`, also `--routing` on `server.server` and `ROUTING=` on `make dev` / `make start`. Default `legacy` | A runtime toggle in the UI: more code, and the mode would change mid-conversation |
| 2 | Data between modes | One shared data directory. `records` keeps a records file **beside** `roster.json` and also writes new names into `roster.json`. `legacy` never touches the records file. On start, `records` imports any roster names it doesn't have yet | Separate data directories per mode: cleaner isolation, but seven modules hard-code `server/data`, and the Gmail connection and conversation would be split too |
| 3 | Who writes the purpose | The interaction agent, through the required `purpose` argument of `create_agent` | A separate LLM call after each task to rewrite it: one more call per task, and it can be added later if purposes go stale |
| 4 | How records stay current | `recent_work` (last 3 instructions with result snippets) is updated in code on every dispatch and completion. No LLM involved | An LLM-maintained description: costs a call per task |
| 5 | Execution internals | Logs, triggers and the batch manager stay keyed by **name**. The ID lives only in the routing layer. Names are made slug-unique at creation, so name → log is one-to-one for new agents | Re-keying logs and triggers by ID: a migration of every store for no routing gain |
| 6 | Embeddings | `openai/text-embedding-3-small` through OpenRouter's `POST /api/v1/embeddings`, 512 dimensions, pinned to the OpenAI provider. Pure-Python cosine, no new dependencies | A local model (sentence-transformers): a large new dependency. numpy: not needed at 500 × 512 |
| 7 | Retrieval signals | Pinned agents from recent context, embedding similarity and BM25, fused by reciprocal rank fusion. A recency prior exists but has weight 0 by default | Embeddings alone: weak on proper nouns (Keith, AWS) and gives nothing for "reply to that" |
| 8 | A retrieval miss | The interaction agent is told the list is partial. No search tool in version 1. A `search_agents` tool is specified as an option, to add only if dev shows `target_excluded` errors are the main failure | Always offering search: an extra model turn whenever it's used, and the model may over-use it |
| 9 | Legacy stays identical | `system_prompt.md`, `TOOL_SCHEMAS`, `prepare_message_with_history` and `_run_interaction_loop` are not changed. The records mode has its own prompt file and tool list | Editing shared files with flags: changes the baseline's recorded hashes and risks changing the baseline system |

## Overview

What happens on each interaction agent turn in `records` mode:

```
incoming message (user, execution result, or email alert)
  │
  ├─ load unsummarized entries (before recording the new message)
  ├─ build queries ───────────── message text; previous user message + message text
  ├─ pins ────────────────────── agents named in this agent message and in recent result lines
  │
  ├─ active records ≤ full_roster_max ?  ── yes ─▶ candidates = all records, roster order
  │                                       └─ no ──▶ retrieval:
  │                                                   pins first, then RRF over
  │                                                   (embedding rank, BM25 rank, recency rank)
  │                                                   → top K
  ├─ scorer.decide(...) ──────── version 1: pass-through (defer to the interaction agent)
  ├─ render <active_agents shown="k" total="n"> with record entries
  └─ real interaction loop with tools:
       send_message_to_agent(agent_id, instructions)
       create_agent(name, purpose, instructions)
       send_message_to_user, send_draft, wait   (unchanged)
         │
         └─ record updates: last_active, task_count, recent_work; embedding refreshed lazily
```

## Startup switch

### How the user picks a mode

```bash
make dev ROUTING=records
```

```bash
.venv/bin/python -m server.server --routing records
```

`OPENPOKE_ROUTING=records` in `.env` or the shell does the same. Leaving it out runs `legacy`, which is today's system.

To try retrieval without 25 agents, lower the full-roster threshold. With 3, any roster of 4 or more active agents goes through retrieval (and makes one small embedding call per turn):

```bash
OPENPOKE_FULL_ROSTER_MAX=3 make dev ROUTING=records
```

`OPENPOKE_FULL_ROSTER_MAX` must be an integer of 0 or more; `0` means always retrieve. Unset or empty uses the default in `RetrievalParams` (25). Any other value stops the server at startup with an error naming the variable. `legacy` ignores it.

### Implementation

- **`server/config.py`:** add `routing_mode: str` to `Settings` with `Field(default_factory=lambda: os.getenv("OPENPOKE_ROUTING", "legacy").strip().lower())`. It has to be `default_factory`, not `default=os.getenv(...)`, because the existing fields read the environment when the class is defined, before `server.py` has parsed its arguments. Add a validator that allows only `legacy` and `records` and raises `ValueError` with the allowed values otherwise. Also add `embedding_model: str = "openai/text-embedding-3-small"` and `embedding_dimensions: int = 512`.
- **`full_roster_max` setting:** `Settings.full_roster_max: int` reads `OPENPOKE_FULL_ROSTER_MAX` through `default_factory`, and falls back to `RetrievalParams().full_roster_max`, so the default lives only in `params.py`. A validator (with `validate_default=True`) accepts integers of 0 or more and raises `ValueError` naming the variable otherwise. `RecordsRouting` takes `full_roster_max` from the setting, not from the dataclass default. A bad value in either variable stops startup with `Invalid configuration: ...` (`server/app.py` and `server/server.py` turn the validation error into `SystemExit`).
- **`server/server.py`:** add `--routing {legacy,records}`. Parse the arguments **before** importing `server.app`: move `from .app import app` into `main()` after parsing. If `--routing` is given, set `os.environ["OPENPOKE_ROUTING"]` and call `get_settings.cache_clear()`. Setting the environment variable is what makes `--reload` work, because uvicorn's reload worker re-imports `server.app:app` in a child process that inherits the environment.
- **`Makefile`:** `ROUTING ?=`, and in `dev` and `start` add `$(if $(ROUTING),--routing $(ROUTING),)` to the server command. Add `ROUTING` to the help text. Update [makefile.md](makefile.md).
- **Startup log:** one line at app start, for example `Routing mode: records (embeddings openai/text-embedding-3-small@512, K=8, full_roster_max=25)`, so it's visible in `make logs` which system is running. The `full_roster_max` shown is the one in effect, after `OPENPOKE_FULL_ROSTER_MAX`. In `legacy` the line is `Routing mode: legacy`.
- **`/api/v1/meta`:** add `routing_mode` to `RootResponse` so the UI or `curl` can confirm the mode. The web UI itself doesn't change.
- **Reading the mode:** code reads `get_settings().routing_mode` when a runtime is created, never at import time.

### Data when switching modes

All modes share `server/data/`. The records mode adds two files under `server/data/execution_agents/`: `agents.json` (records) and `embeddings.json` (the vector cache).

| Situation | What happens |
| --- | --- |
| First start in `records` with an existing legacy roster | Every name in `roster.json` gets a record through [import](#import-from-the-legacy-roster). Logs, triggers and the conversation are untouched |
| `records` creates an agent | A record is written, and the name is also added to `roster.json` |
| Back to `legacy` | `legacy` sees every agent by name in `roster.json`, including ones created in `records` mode. It ignores `agents.json` |
| Agents created in `legacy` after `records` ran | Imported on the next `records` start |
| `DELETE /api/v1/chat/history` (reset) | Also deletes `agents.json` and `embeddings.json`, in both modes |

Conversation history is shared, so a conversation started in one mode can continue in the other. That's useful for trying both on the same state, but it means the two modes aren't isolated. For a clean comparison by hand, reset before switching.

## Agent records

### Schema

`server/services/agents/records.py`:

```python
@dataclass
class WorkSnippet:
    instructions: str          # ≤ 200 chars, cut at a word boundary with "…"
    result: str                # ≤ 150 chars; "" until the agent finishes
    at: str                    # "YYYY-MM-DD HH:MM:SS", user timezone, time of dispatch

@dataclass
class AgentRecord:
    agent_id: str              # "ag_" + secrets.token_hex(4), e.g. "ag_1f3a9c2e"; never reused
    name: str                  # display name and the key for logs and triggers
    slug: str                  # log_store._slugify(name); unique across records
    purpose: str               # ≤ 200 chars; "" for imported agents
    recent_work: list[WorkSnippet]   # newest last, at most 3
    created_at: str            # "YYYY-MM-DD HH:MM:SS"
    last_active: str           # last delegation from the interaction agent
    task_count: int
    status: str = "active"     # only "active" in version 1; "archived" reserved for version 2
    aliases: list[str] = field(default_factory=list)   # legacy names that share this record's log
    purpose_source: str = "create"   # "create" | "import" | "backfill"
```

Version 2 adds `last_run` (any execution, including trigger runs) for archiving. Version 1 doesn't track trigger runs.

### Store

`AgentRecordStore(path)` stores `{"version": 1, "records": [...]}` in `agents.json`, in creation order.

- **Writes** are atomic: write to `agents.json.tmp`, then `os.replace`. A `threading.Lock` guards the in-memory state. Tool handlers and completion callbacks both run on the event loop thread, but the log store already uses threading locks, so this matches it.
- **Methods:** `load()`, `all(status="active")`, `get(agent_id)`, `find_by_name_or_slug(text)` (exact name, then alias, then slug), `create(name, purpose, now) -> AgentRecord` (raises `SlugCollision(existing)`), `touch_dispatch(agent_id, instructions, now)`, `record_result(agent_id, result_text)`, `clear()`.
- **`touch_dispatch`** sets `last_active`, adds 1 to `task_count`, appends a `WorkSnippet` and drops the oldest past 3.
- **`record_result`** fills `result` on the newest snippet that has none.
- **Singleton:** `get_agent_records()` at `server/data/execution_agents/agents.json`, the same pattern as `get_agent_roster()`.

### Import from the legacy roster

`reconcile_from_roster(store, roster, log_store)` runs at app start in `records` mode, and is a no-op in `legacy`. For each name in `roster.json` with no record (matching by name or alias):

- If its slug matches an existing record's slug, add the name to that record's `aliases`. The two names already share one log file (cause I4), so they're one agent's history.
- Otherwise create a record. `purpose = ""` and `purpose_source = "import"`. `created_at` is the first log entry's timestamp. `last_active` is the last `agent_request` timestamp. `task_count` is the number of `agent_request` entries. `recent_work` holds the last 3 `agent_request` entries, each paired with the next `agent_response`.
- If the agent has no log, use the current time and empty work.

### Retrieval text and prompt rendering

`server/services/agents/text.py`. One function feeds the index and BM25, and a second renders the prompt. The harness uses both.

```python
def retrieval_text(r) -> str:
    # name, purpose, then up to 3 snippets, newest first; ≤ 1,500 chars
    lines = [r.name]
    if r.purpose: lines.append(r.purpose)
    for w in reversed(r.recent_work):
        lines.append(w.instructions + (f" → {w.result}" if w.result else ""))
    return "\n".join(lines)[:1500]
```

The prompt entry shows only the newest snippet, to keep tokens down (`render_recent = 1`):

```xml
<agent id="ag_1f3a9c2e" name="AWS Invoice Lookup" last_active="2026-10-20" tasks="3">
<purpose>Finds the user's AWS invoices and answers billing questions about them.</purpose>
<recent>Check whether the October invoice was paid → No payment recorded yet.</recent>
</agent>
```

- Escape values with `html.escape(..., quote=True)`.
- Leave out `<purpose>` when it's empty, and `<recent>` when there's no work.
- `last_active` shows the date only.

Estimated size: about 70 to 90 tokens per entry, against about 10 for `<agent name="..." />`. That's a guess to be measured by the token probe. At K = 8 the block is about 700 tokens, less than the names-only roster above about 70 agents. With the full roster at N = 200 it's about 16,000 tokens, which is why `records_full` is only an ablation.

## ID routing tools

`server/agents/interaction_agent/tools_records.py`. In `records` mode these replace only the routing tool. `send_message_to_user`, `send_draft` and `wait` are the same functions and schemas as today.

### Schemas

```json
{
  "type": "function",
  "function": {
    "name": "send_message_to_agent",
    "description": "Give a task to an existing execution agent from <active_agents>. The agent keeps its history, so prefer the agent that already holds the relevant context.",
    "parameters": {
      "type": "object",
      "properties": {
        "agent_id": {"type": "string", "description": "The id attribute of an agent in <active_agents>, e.g. 'ag_1f3a9c2e'."},
        "instructions": {"type": "string", "description": "Instructions for the agent to execute."}
      },
      "required": ["agent_id", "instructions"],
      "additionalProperties": false
    }
  }
}
```

```json
{
  "type": "function",
  "function": {
    "name": "create_agent",
    "description": "Start a new execution agent for work no agent in <active_agents> covers, and give it its first task.",
    "parameters": {
      "type": "object",
      "properties": {
        "name": {"type": "string", "description": "Short human-readable name for the ongoing work (e.g. 'Vercel Job Offer', 'Email to Sharanjeet'). At most 60 characters."},
        "purpose": {"type": "string", "description": "One sentence on the ongoing work this agent owns: the person, company or thread, and the kind of task. Used to find the agent again later. At most 200 characters."},
        "instructions": {"type": "string", "description": "Instructions for the agent's first task."}
      },
      "required": ["name", "purpose", "instructions"],
      "additionalProperties": false
    }
  }
}
```

### Behaviour

**`send_message_to_agent(agent_id, instructions)`:**

1. Resolve the agent: `store.get(agent_id)`. If that fails, try `find_by_name_or_slug(agent_id)`, because models sometimes pass the name. A match through this fallback is logged as `resolved_by="name"`.
2. If nothing matches, return `ToolResult(success=False, payload={"error": "Unknown agent_id 'x'. Use an id from <active_agents>, or create_agent for new work."})` and create nothing. This is the change that removes silent spawns (I3).
3. Otherwise: `touch_dispatch`, `get_execution_agent_logs().record_request(record.name, instructions)`, and dispatch through the same `ExecutionBatchManager.execute_agent(record.name, instructions)` background task as today. When the result arrives, call `store.record_result(record.agent_id, result.response)` inside that task.
4. Return `{"status": "submitted", "agent_id": ..., "agent_name": ..., "new_agent_created": false}`.

**`create_agent(name, purpose, instructions)`:**

1. Strip `name` and `purpose`. An empty name returns an error. Names over 60 characters are cut.
2. An empty purpose doesn't fail the call. It falls back to the first 200 characters of `instructions` with `purpose_source="instructions_fallback"`, and the fallback is logged and counted, so prompt problems are visible.
3. If the slug collides with an existing record or alias, return `ToolResult(success=False, payload={"error": "An agent named 'X' (id ag_...) already exists. Use send_message_to_agent with that id, or choose a different name.", "existing_agent_id": "ag_..."})`. This fixes I4 for new agents. It costs one extra loop iteration when it happens, which is rare and is counted.
4. Otherwise: `store.create`, `get_agent_roster().add_agent(name)` (keeps legacy in sync), `record_request`, `touch_dispatch`, dispatch, and the same completion callback.
5. Return `{"status": "submitted", "agent_id": ..., "agent_name": name, "new_agent_created": true}`.

**Embedding refresh** never blocks a tool call. The index re-embeds stale records lazily during the next retrieval (see [Index](#index)).

**Known small gap:** `_run_interaction_loop` counts `execution_agents` from the `agent_name` argument of `send_message_to_agent`. It isn't changed (decision 9), so `InteractionResult.execution_agents_used` undercounts in `records` mode. Nothing reads it today.

## Records-mode prompt

- **`server/agents/interaction_agent/system_prompt_records.md`:** a copy of `system_prompt.md` with only the "Send Message to Agent Tool Usage" section replaced, between the marker comments `<!-- routing:start -->` and `<!-- routing:end -->`. The markers are in the new file only. A test checks that the text outside the markers equals `system_prompt.md`, so later edits to the main prompt can't drift silently.
- **Replacement section**, to be tuned on dev only (the prompt hash is recorded with every run):

```markdown
Send Message to Agent and Create Agent Tool Usage

- Execution agents, reached through `send_message_to_agent` and `create_agent`, are your primary tools for accomplishing tasks. They have tools for a wide variety of tasks, and you should use them often, even if you don't know if an agent can do it (tell the user you're trying to figure it out).
- Agents cannot communicate with the user, and you should always communicate with the user yourself.
- `<active_agents>` lists existing agents with an `id`, a `name`, their `purpose` and their most recent task. When `shown` is smaller than `total`, the list holds only the agents most related to the new message; others exist but were judged unrelated.
- IMPORTANT: Prefer an existing agent over a new one unless the tasks can run in parallel. If an agent found an email and the user wants to reply to it, send the follow-up to that agent with `send_message_to_agent` and its `agent_id`. Reuse an agent whose name is unrelated if it holds useful context.
- Use `create_agent` only for work that no listed agent covers. Give it a short name and a one-sentence purpose naming the person, company or thread and the kind of work, so the agent can be found again later.
- IMPORTANT: Your goal should be to work in parallel as much as possible. If the user asks for a complicated task, split it into as many concurrent calls as possible.
- IMPORTANT: Tell agents what to do, not how. Avoid technical descriptions about tools with both the user and the agent.
- If you intend to call multiple tools and there are no dependencies between the calls, make all of the independent calls in the same message.
- Always let the user know what you're about to do (via `send_message_to_user`) **before** calling these tools.
```

- **Message builder** (`server/agents/interaction_agent/records_prompt.py`): `prepare_records_messages(latest_text, transcript, message_type, rendered_agents, shown, total)` returns the same structure as `prepare_message_with_history`: `<conversation_history>`, then `<active_agents shown="k" total="n">` with the rendered entries (or `None`), then `<new_user_message>` or `<new_agent_message>`. It reuses `_render_conversation_history` and `_render_current_turn` from `agent.py` (import them, don't copy them).

## Candidate selection

`server/services/routing/`. Pure, async functions over plain data, so the server and the harness run the same code. Nothing in this package reads files or settings directly. Callers pass in records, entries, parameters and an embedder.

### Inputs and outputs

```python
@dataclass(frozen=True)
class RecordView:              # what selection needs; built from AgentRecord or from the harness AgentView
    agent_id: str
    name: str
    purpose: str
    recent_work: tuple[WorkSnippet, ...]
    last_active: str           # "" if unknown

@dataclass(frozen=True)
class EntryView:
    tag: str                   # user_message | agent_message | poke_reply | wait
    payload: str

@dataclass
class CandidateSet:
    mode: str                  # "full" | "retrieved" | "retrieved_lexical_fallback" | "empty"
    shown: list[str]           # agent_ids rendered into the prompt, in render order
    ranked: list[str]          # pins + fused order, first 20, for recall@k
    excluded: list[str]        # active agent_ids not shown
    pinned: list[str]
    scores: dict[str, dict]    # agent_id -> {"sem": float|None, "lex": float|None, "rrf": float}
    queries: list[str]
    embed_calls: int

class Embedder(Protocol):
    model: str
    dimensions: int
    async def embed(self, texts: list[str], purpose: str) -> list[list[float]]: ...
```

### Parameters

`RetrievalParams` in `server/services/routing/params.py`, a frozen dataclass. These defaults are starting points to tune on dev, not decisions:

| Param | Default | Meaning |
| --- | --- | --- |
| `full_roster_max` | 25 in production (a guess until the baseline); `OPENPOKE_FULL_ROSTER_MAX` overrides it in the server; set per config in evals | Show every record when there are at most this many active ones |
| `k` | 8 | Records shown when retrieving |
| `max_pinned` | 3 | Pinned agents counted inside K |
| `pin_lookback` | 3 | Recent `agent_message` entries scanned for result lines |
| `use_pins` / `use_semantic` / `use_lexical` | true / true / true | Channel switches, for ablations |
| `w_sem`, `w_lex`, `w_rec` | 1.0, 1.0, 0.0 | RRF weights. Recency is off by default because of the recency-lock risk |
| `rrf_k` | 60 | Standard RRF constant |
| `query_with_previous_user_message` | true | Also embed "previous user message + message" |
| `render_recent` | 1 | Snippets shown per prompt entry |

The server uses these defaults. Eval configs override them through `method.params`. `rrf_k`, `k1` and `b` are standard values and aren't tuned. The rest are tuned on dev as described in the [experiment plan](#experiment-plan-for-version-1).

**Keeping the server in step with what was tested.** When the test config is frozen, copy its values into the defaults here in the same change. A unit test loads the frozen test config and checks that its retrieval params equal `RetrievalParams()`, so `make dev ROUTING=records` runs the version that was measured.

### Steps

**1. Short-circuits.** No active records: mode `empty`. `len(active) ≤ full_roster_max`: mode `full`. In `full` mode, `shown` and `ranked` are all ids in roster order, nothing is excluded, and no embedding call is made.

**2. Pins** (non-embedding signal for implicit follow-ups):

- **Execution results:** if `message_type == "agent"`, parse each line of the incoming message with `^\[(SUCCESS|FAILED)\] (.+?): ` and pin agents whose name or alias matches the captured name.
- **Recent result lines:** scan the last `pin_lookback` `agent_message` entries in the unsummarized entries, newest first, with the same pattern, and pin the matches.
- Keep the order, drop duplicates, and stop at `max_pinned`.
- Email watcher alerts (`Important email watcher notification:` prefix) have no agent name, so they only get recent-result pins.
- Names are matched exactly, then by slug. The `[STATUS] name:` lines come from `_format_batch_payload`, which uses the execution agent's name, so this is reliable.

**3. Queries:**

- `q_msg`: the message text. For execution results, strip the `[STATUS] name: ` prefix from each line. For email alerts, strip the notification prefix.
- `q_ctx`: if `query_with_previous_user_message` is on and there's an earlier `user_message` in the unsummarized entries, `"<previous user message>\n<q_msg>"`.
- Cut each to 2,000 characters.

**4. Semantic channel.**

- One embedding call holds the queries plus every record whose cached vector is stale (see [Index](#index)).
- Vectors are L2-normalized at storage, so cosine is a dot product.
- `sem(a) = max(cos(q_msg, v_a), cos(q_ctx, v_a))`. Rank all active records by `sem`.

**5. Lexical channel (BM25).**

- Tokens: `re.findall(r"[a-z0-9]+", text.lower())`, minus a stopword list. Use the scorer's list (to, for, the, a, an, of, and, with, my, re) plus: is, it, that, this, on, in, at, me, can, you, please, i.
- `k1 = 1.2`, `b = 0.75`. The corpus is the active records' `retrieval_text`, computed per turn (500 documents of about 60 tokens is cheap). The query is the token union of `q_msg` and `q_ctx`.
- Only records with a score above 0 get a lexical rank.

**6. Recency channel.** Rank by `last_active`, newest first, skipping records with an empty value. It's used only when `w_rec > 0`.

**7. Fusion.** `rrf(a) = Σ_c w_c / (rrf_k + rank_c(a))`, with 1-based ranks, over the channels where `a` has a rank. Ties are broken by `last_active`, newest first, then `agent_id`.

**8. Output.**

- `ranked = pins + [fused order without pins]`, cut to 20.
- `shown = ranked[:k]`.
- `excluded` = active ids not in `shown`.
- Render order is `shown` order (pins first, then by relevance). Position bias is a known LLM effect, so the harness's position breakdown should be read with this in mind.

**9. Failure.** If the embedding call fails after retries, set `use_semantic` off for this turn. The mode becomes `retrieved_lexical_fallback`, and the failure is logged and counted. It does **not** fall back to the full roster, which could be thousands of tokens at large N. That's a choice: a turn with lexical-only retrieval is worse, but bounded.

### Index

`EmbeddingIndex` in `server/services/routing/embeddings.py`. It maps `agent_id` to `{"text_sha256", "model", "dimensions", "vector"}`.

- A record's vector is **stale** when `sha256(retrieval_text(r))`, the model or the dimensions differ from what's stored.
- Stale records are embedded in the same call as the turn's queries, so one call per turn covers both.
- **Production:** stored in `embeddings.json`, written atomically. About 512 floats × 500 agents, roughly 2.5 MB as JSON. That's acceptable. Use `round(x, 6)`.
- **Harness:** an in-memory index pre-filled from the method's cache in `prepare()`.
- Batching is at most 64 inputs per call. Start-up after an import can need several calls.

**`OpenRouterEmbedder`:**

- `POST https://openrouter.ai/api/v1/embeddings` with `{"model", "input": [...], "dimensions": 512, "encoding_format": "float", "provider": {"order": ["openai"], "allow_fallbacks": false}}`.
- Uses the existing `OPENROUTER_API_KEY` and headers from `openrouter_client`.
- Timeout 10 s, 2 retries on 429, 5xx and network errors.
- Orders vectors by `data[].index`.

Endpoint and fields checked against the [OpenRouter embeddings reference](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request.md) on 2026-10-26. The price, $0.02 per million input tokens, is from `GET /api/v1/embeddings/models` on the same date. A turn embeds about 100 tokens, so the cost is negligible. The **latency** added per turn isn't known: it's a guardrail metric, measured by the harness.

## Scorer slot

`server/services/routing/scorer.py`. Version 1 defines the interface and implements only the pass-through scorer. Later specs add the options in [Scorer options](agent-overload.md#scorer-options) behind this interface.

```python
@dataclass(frozen=True)
class ScoringInput:
    message_text: str
    message_type: str
    entries: tuple[EntryView, ...]
    candidates: tuple[RecordView, ...]       # in CandidateSet.shown order
    candidate_set: CandidateSet

@dataclass
class ScoringDecision:
    kind: str                                # "defer" | "reuse" | "create" | "ask"
    agent_id: str | None = None              # for "reuse"
    confidence: float | None = None
    candidates: list[str] | None = None      # a scorer may reorder or trim the shown list (rerankers)
    llm_calls: list = field(default_factory=list)   # model calls the scorer made, for cost accounting
    diagnostics: dict = field(default_factory=dict)

class Scorer(Protocol):
    name: str
    version: str
    async def decide(self, inp: ScoringInput) -> ScoringDecision: ...

class InteractionAgentScorer:
    name, version = "interaction_agent", "1"
    async def decide(self, inp): return ScoringDecision(kind="defer")
```

The contract for later scorers, fixed now so they fit without reshaping the pipeline:

- `defer`: render `candidates` (or `candidate_set.shown`) and let the interaction agent route. This is version 1.
- `reuse`, `create` and `ask` with a confidence are **advisory** until a later spec chooses between two consumers. *Hint* adds a `<routing_hint agent_id="..." confidence="..."/>` line to the prompt. *Enforce* skips the interaction agent's routing decision. That choice is left to the scorer spec, because enforcing changes D1 (routing taken out of the generative agent) and needs its own experiment.
- The selected scorer is a config value: `scorer: {"name": "interaction_agent", "params": {}}` in eval configs, and `routing_scorer` in `Settings` later. Version 1 doesn't add the setting.

## Wiring into the interaction runtime

A small strategy object keeps both modes on one runtime. `server/agents/interaction_agent/routing.py`:

```python
class RoutingStrategy(Protocol):
    name: str
    def build_system_prompt(self) -> str: ...
    def tool_schemas(self) -> list[dict]: ...
    async def prepare_messages(self, latest_text: str, transcript: str, message_type: str,
                               entries: list[EntryView]) -> list[dict]: ...
    def handle_tool_call(self, name: str, arguments) -> ToolResult: ...

class LegacyRouting:     # returns exactly what today's code returns
    build_system_prompt   -> agent.build_system_prompt()
    tool_schemas          -> tools.get_tool_schemas()
    prepare_messages      -> agent.prepare_message_with_history(latest_text, transcript, message_type)
    handle_tool_call      -> tools.handle_tool_call(name, arguments)

class RecordsRouting:    # reads records, selects candidates, scores, renders, logs the CandidateSet
    ...

def get_routing_strategy() -> RoutingStrategy:  # by get_settings().routing_mode
```

Changes to `server/agents/interaction_agent/runtime.py`:

- `__init__` sets `self.routing = get_routing_strategy()` and `self.tool_schemas = self.routing.tool_schemas()`.
- `execute` and `handle_agent_message` load `entries_before` (the unsummarized entries, the same list the transcript renders) right after `transcript_before`, before recording the new message. They then call `self.routing.build_system_prompt()` and `await self.routing.prepare_messages(...)`.
- `_execute_tool` calls `self.routing.handle_tool_call(...)` instead of the module-level `handle_tool_call`.
- `_run_interaction_loop`, `_make_llm_call` and the parsing helpers are **not changed**.

The eval harness subclasses this runtime without calling `__init__` and overrides `_make_llm_call` and `_execute_tool`, so `names_only` keeps working unchanged.

**Logging:** in `records` mode, log each turn's `CandidateSet` at INFO (mode, shown ids and names, pinned, total), and the scores at DEBUG. When you use the UI, `make logs` then shows what the interaction agent was offered on every turn.

**Reset:** `clear_history` in `server/routes/chat.py` also calls `get_agent_records().clear()` and deletes `embeddings.json`.

## Harness integration

The harness lives in the phase 1 branch (`evals/agent_overload/`). These changes are small and additive. They must not change `names_only` results. Bump `harness_version` to `1.1.0`.

**Timing.** Land the harness changes **after** the phase 1 baseline has run, so the baseline runs on harness 1.0.0 as designed. The server-side work above can start right away from `main`, because `legacy` mode is byte-identical. Don't merge server changes into the phase 1 branch before its baseline run: the baseline records a hash of `server/`.

### Interface additions (`harness/methods/base.py`)

1. `RoutingInput.now: str = ""`: the turn's message timestamp, set by the runner from the case or turn. Used for `last_active` dates in rendering and the recency channel.
2. `AgentView.extra: tuple[tuple[str, str], ...] = ()` and `Delegation.extra: dict = field(default_factory=dict)`. When a method creates an agent with `extra={"purpose": ...}`, the runner stores it on the new agent in carried-forward mode and passes it back in later views. That's how a purpose written by `create_agent` survives to later turns without the method keeping state between turns.
3. `ModelClient.embed(*, purpose, model, inputs, dimensions, provider) -> (list[list[float]], CallRecord)`:
   - It records usage and cost like `chat`, and goes through the spend tracker and rate limiter.
   - `FakeClient` returns deterministic feature-hashed bag-of-words vectors (tokens hashed into `dimensions` buckets, then normalized). Lexically similar texts get similar vectors, so the fake end-to-end test can check recall plumbing.
   - Add `openai/text-embedding-3-small` to `configs/pricing.json`.

### Method `records_retrieval` version 1

`harness/methods/records_retrieval.py`, registered in `run.py:make_method`.

- **`prepare(agents)`:**
  - Builds `RecordView`s from `AgentView`s. `recent_work` comes from the last 3 `work_log` items, with the same truncation as production. `last_active` is filled per turn from the view.
  - With `seed_purposes: "backfill"`, every agent gets a purpose from `write_purpose(name, first_instructions)` in `server/services/agents/purpose.py` (below), cached at `evals/agent_overload/cache/records_retrieval/1/purposes.jsonl`, keyed by `agent_id` and `sha256(prompt + name + instructions)`.
  - With `"none"`, purposes are `""`.
  - Then it embeds every record's `retrieval_text`, cached at `.../embeddings.jsonl` and keyed by `sha256(model|dimensions|text)`.
  - Both cache files' hashes go into `describe()`.
- **`route(inp)`:**
  - Builds `RecordView`s from `inp.roster`. A view's purpose is `extra["purpose"]` if present, else the cached backfill, else `""`.
  - Runs `select_candidates` (the production function) with an `Embedder` adapter over `ModelClient.embed` (purpose `embed_query`), then the configured scorer.
  - Renders with `retrieval_text`, `render_agent_entry` and `prepare_records_messages`, using the records system prompt and tool schemas.
  - Runs the real loop through the `names_only` pattern: the `HarnessInteractionRuntime` subclass with stubs.
- **New stubs**, with the same signatures and payloads as `tools_records.py`:
  - `send_message_to_agent(agent_id, instructions)` resolves against the turn's views (id, then name, then slug). On a match it records `Delegation(agent_key=<agent_id>)`. An unknown id returns the production error payload and is recorded in `invalid_calls` with `error="unknown agent_id"`.
  - `create_agent(name, purpose, instructions)` checks slug collisions against the views plus names created earlier in the turn. A collision returns the production error and is recorded in `diagnostics["rejected_creates"]`; it's a recoverable refusal, not an invalid call. Otherwise it records `Delegation(agent_key="new:<name>", extra={"purpose": purpose})`.
- **Diagnostics:** `{"candidates": ranked, "excluded": excluded, "pinned": pinned, "candidate_mode": mode, "resolved_by_name": n, "rejected_creates": [...], "purpose_fallbacks": n}`. The existing scorer then gives recall@k and `target_excluded` for free.
- **`describe()`:** params, `system_prompt_records.md` sha256, records tool schemas sha256, the embedding model and dimensions, the scorer name and version, the cache hashes, and the method source sha256.

**Purpose backfill** (`server/services/agents/purpose.py`, shared so harness and production use the same prompt): one call to the summarizer model.

- System prompt: *"You write the purpose line for a background worker in a personal assistant. Given the worker's name and its first task, write one sentence of at most 25 words naming the person, company or thread and the kind of ongoing work. Output only the sentence."*
- User message: `Name: ...\nFirst task: ...`.
- In the harness it goes through `ModelClient.chat` with purpose `purpose_backfill`. The production entry point is an optional CLI, `python -m server.services.agents.purpose --backfill`. It's paid, run by the user, and fills purposes for imported agents. It's not needed for version 1 to work.

A fidelity gap to note in results: seeded agents' purposes come from backfill, while in production they'd come from `create_agent` at creation time. Both see the same information (the first task), but the wording may differ.

### Configs

The `method` block of each config:

- **`configs/v1_records_full.json`**, `{"name": "records_retrieval", "version": "1", "params": {"full_roster_max": 100000, "seed_purposes": "backfill", "scorer": {"name": "interaction_agent"}}}`: hypothesis H1, records and ID routing with no retrieval.
- **`configs/v1_records_retrieval.json`**, `{"name": "records_retrieval", "version": "1", "params": {"full_roster_max": 0, "k": 8, "max_pinned": 3, "w_sem": 1.0, "w_lex": 1.0, "w_rec": 0.0, "use_pins": true, "seed_purposes": "backfill", "embedding": {"model": "openai/text-embedding-3-small", "dimensions": 512}, "scorer": {"name": "interaction_agent"}}}`: hypothesis H2, retrieval at every N.
- **The test config** sets `full_roster_max` to the value chosen on dev (below).

Everything else is identical to `baseline_names_only.json`. Variants (H3 `use_pins: false`, H4 `seed_purposes: "none"`) are param changes on dev only. A test run uses one fixed config, per the test ledger rule.

### Retrieval probe (cheap tuning, dev only)

`evals/agent_overload/retrieval_probe.py`.

- Loads the frozen fixtures, builds the roster for each (case, N) exactly as the runner does, and runs **only** `select_candidates`. No routing model calls.
- Reports recall@k for k in 1, 3, 5, 8, 10, 12, 20, overall and by query style, message subtype, `target_name_visible`, history type and N. Also reports the share of hits that came only from pins.
- Costs only embeddings (cents) and the one-off purpose backfill (estimated under $0.20 for the dev agents).
- It reads labels, so it **refuses `--split test`**. Same `--dry-run` and `--confirm-spend` rules as `run.py`.
- Single-turn cases only. Sequences are measured by the routing runs.

This is where K, the weights, pins and the query options get tuned. A full routing run costs about 50 times as much.

## Experiment plan for version 1

All on dev until the last step. The user runs every paid command. Costs are estimates, to be replaced with measured ones after the first `dev-quick`.

| Step | What | Settles | Est. cost |
| --- | --- | --- | --- |
| 1 | Free checks: unit tests, fake-model end-to-end with `records_retrieval`, legacy parity tests | Plumbing | $0 |
| 2 | Purpose backfill and index for dev agents (`prepare` through the probe) | | < $0.20 |
| 3 | Retrieval probe on dev at N = 50, 100, 200 with a few settings: pins on and off, BM25 on and off, `q_ctx` on and off, `w_rec` in {0, 0.5} | H3; K = the smallest value in {5, 8, 12} with dev recall@K ≥ 0.95 at N = 200 (if none reaches it, 12, and say so); channel weights | < $0.10 total |
| 4 | `dev-quick` with `v1_records_full` | H1 on dev, and its token cost | about $1.20 |
| 5 | `dev-quick` with `v1_records_retrieval` at the tuned K, plus one variant with `seed_purposes: "none"` | H2 and H4 on dev | about $0.40 each |
| 6 | Choose `full_roster_max` (rule below) and freeze the test config | | $0 |
| 7 | `test` once with the frozen config, then `compare.py` against the baseline | Version 1 result | about $5 (lower than baseline at large N, higher at small N) |

**Rule for `full_roster_max`:** the largest N in the baseline's **dev** sweep that's below the dev accuracy drop point, using the drop-point definition in the experiment design. The dev split keeps test out of tuning. If the baseline has no drop point, use the largest N at which `records_full` and `records_retrieval` are within 2 points on dev at N = 10 and 200. If even that's unclear, bring it to the user before freezing.

**Budget check.** Steps 2 to 7 come to about $7.50 against the plan's $5 for iteration and $6 for the version 1 phase 1 test run. That fits, but leaves little room for repeated dev runs. If the first `dev-quick` costs more than estimated, cut step 5's variant first, then run `records_full` at N = 200 only.

**What gets recorded** in [agent-overload.md](agent-overload.md#experiments) afterwards: the probe's recall table, the dev comparisons for H1 to H4 with CIs, the chosen K and `full_roster_max` with their rule, and the test comparison.

## Files

**New:**

| Path | What |
| --- | --- |
| `server/services/agents/__init__.py`, `records.py`, `text.py`, `purpose.py` | Records, store, import, rendering, purpose backfill |
| `server/services/routing/__init__.py`, `params.py`, `pins.py`, `query.py`, `lexical.py`, `embeddings.py`, `candidates.py`, `scorer.py` | Candidate selection and the scorer slot |
| `server/agents/interaction_agent/routing.py` | `RoutingStrategy`, `LegacyRouting`, `RecordsRouting` |
| `server/agents/interaction_agent/records_prompt.py` | Records-mode message builder |
| `server/agents/interaction_agent/tools_records.py` | Records-mode tool schemas and handlers |
| `server/agents/interaction_agent/system_prompt_records.md` | Records-mode system prompt |
| `server/tests/` (unittest) | Server tests below. There's no server test directory today; use `python -m unittest discover server/tests` |
| `evals/agent_overload/harness/methods/records_retrieval.py`, `retrieval_probe.py`, `configs/v1_records_*.json`, tests | Harness side |

**Changed:** `server/config.py`, `server/server.py`, `Makefile`, `server/agents/interaction_agent/runtime.py` (the three call sites only), `server/routes/chat.py` (reset), `server/routes/meta.py` and `server/models/meta.py` (`routing_mode`), the startup hook in `server/app.py` (import, log line), `evals/agent_overload/harness/methods/base.py`, `harness/llm.py`, `harness/runner.py` (`now`, `extra`), `run.py` (`make_method`), `configs/pricing.json`, [makefile.md](makefile.md), the experiment runbook (a "Version 1" section), [README.md](README.md) if new docs are added.

**Must not change:** `server/agents/interaction_agent/system_prompt.md`, `TOOL_SCHEMAS` and the legacy tool functions in `tools.py`, `prepare_message_with_history` and the `_render_*` helpers in `agent.py`, `_run_interaction_loop`, the log store, triggers and execution agents.

## Tests

`unittest`, no network, no new dependencies.

**Server:**

- **Legacy is untouched:** with `routing_mode="legacy"`, `InteractionAgentRuntime` gives the same system prompt, tool schemas and messages as calling the module functions directly. The sha256 of `system_prompt.md` and of `json.dumps(TOOL_SCHEMAS, sort_keys=True)` match the values recorded at the start of implementation.
- **Prompt drift:** `system_prompt_records.md` outside the routing markers equals `system_prompt.md`.
- **Mode switch:** `OPENPOKE_ROUTING` unset gives `legacy`. `records` gives `records`. A bad value raises. `server.server --routing records` sets the environment before `server.app` is imported (check with a subprocess and `/api/v1/meta`, or by patching `uvicorn.run`).
- **Full-roster threshold:** `OPENPOKE_FULL_ROSTER_MAX` unset gives 25, a valid value is used (also by `RecordsRouting`), and a negative or non-integer value raises.
- **Store:** create, collision, alias, `touch_dispatch` keeping 3 snippets, `record_result` filling the right snippet, atomic write, clear.
- **Import:** a temp roster plus temp logs with `Email Keith` and `email-keith` gives one record with an alias. Timestamps, counts and snippets come from the logs.
- **Tools:** an unknown id errors and creates nothing; a name passed as id resolves; a create collision errors with the existing id; an empty purpose falls back; a create adds to `roster.json`. Execution dispatch is patched out.
- **Candidates:**
  - `full` and `empty` short-circuits.
  - Pins from execution results and from recent result lines, deduped and capped.
  - BM25 prefers the record with the shared proper noun.
  - RRF ordering and tie-breaks.
  - `shown` + `excluded` = all active.
  - `ranked` is capped at 20.
  - Stale-vector detection embeds only changed records.
  - Embedder failure gives `retrieved_lexical_fallback`.
  - All with a fake embedder.
- **Rendering:** escaping, omitted empty fields, the `shown` and `total` attributes, `None` for an empty roster.

**Harness:**

- **Stub parity:** each records stub returns the same `ToolResult` payload as the real tool pointed at temp paths.
- **`names_only` unchanged:** the existing tests pass, and a fake-model run gives identical `turns.jsonl` before and after the interface additions.
- **Carried `extra`:** a purpose written by `create_agent` on turn t shows up in the view on turn t + 1.
- **Fake end-to-end** with `records_retrieval`: diagnostics present, recall@k computed, `target_excluded` tagged when the target is hidden.
- **Probe:** refuses `--split test`, and `--dry-run` makes no calls.

## Implementation order

1. Records store, import, text rendering, with tests.
2. The routing package (pins, query, BM25, embeddings index, candidates, scorer), with a fake embedder and tests.
3. Records tools, prompt file and message builder, with tests.
4. `RoutingStrategy`, the runtime call sites, the startup switch, the Makefile, meta, reset and the startup log. Legacy parity tests.
5. **The user tries `records` mode in the UI** (`make dev ROUTING=records`, paid but small) and checks `make logs` for candidate sets.
6. Harness additions, the `records_retrieval` method, configs, the probe, and harness tests (fake model only). This happens after the phase 1 baseline has run.
7. Runbook section "Version 1: records and retrieval" with the exact commands for steps 2 to 7 of the experiment plan. The user runs them.

The implementing agent never passes `--confirm-spend` and never runs paid commands, the same as in phase 1.

## Effect on the overload problem

- **Tokens per turn** stop growing with N above `full_roster_max` (I1), but each shown entry is about 8 times larger. Below the threshold, tokens per turn **rise** compared with the baseline.
- **Silent spawns** from near-miss names go away (I3), because reuse needs an ID. Duplicates can still come from the model choosing `create_agent` when it shouldn't. That's what false-spawn rate measures.
- **Log sharing** between slug-equal names (I4) is fixed for new agents and folded into aliases for old ones.
- **New failure mode:** retrieval misses become false spawns (`target_excluded`). The pins and BM25 channels are there to reduce them, and the probe measures them before any routing run.
- **New dependency:** an embedding call on every turn above the threshold. Its latency is a guardrail metric. If OpenRouter's embedding endpoint is down, the system degrades to lexical retrieval rather than failing.

## Implementation notes

Readings of the spec that the implementation had to choose, recorded so the experiment and later versions build on the same ones. Each kept `legacy` and `names_only` unchanged; tests pin both.

**Server**

- `RecordView` has two more fields with defaults: `task_count` (the prompt entry shows `tasks="N"`) and `aliases` (pins match aliases). `CandidateSet` has `error`, the reason the semantic channel was dropped.
- Records no channel ranks are still ordered after the ranked ones, by the tie-break (`last_active`, then `agent_id`), so K fills on lexical-only turns. In `full` and `empty` mode pins, queries and scores stay empty.
- Text cuts collapse whitespace and count the "…" inside the limit. Names over 60 characters are cut without "…". An empty result is stored as "(no response)", so a later result can't fill the wrong snippet.
- Import pairs each `agent_request` with the next unpaired `agent_response`; responses with no open request (trigger runs) are skipped. A log with no requests sets `last_active` to `created_at`.
- The routing markers stay in `system_prompt_records.md` for the drift test but are removed before the prompt is sent. `last_active` is left out of an entry when it's unknown.
- Retrieval reads every cached vector before its first `await`, so a concurrent turn re-embedding the same agent can't swap a vector mid-turn. `EmbeddingIndex(key_by_content=True)` keys vectors by `sha256(model|dimensions|text)` instead of `agent_id`; the harness uses it, since its `a-run-<n>` ids repeat across concurrent sequences with different texts.
- `server/services/agents/purpose.py` holds the backfill prompt, its cache key and the output cleanup. The optional production backfill CLI isn't built.

**Harness (version 1.1.0)**

- Embeddings go through the run's API: OpenAI's `/v1/embeddings` for `models.api: "openai"` (the baseline's setting since phase 1 moved runs off OpenRouter), else OpenRouter with the provider pinned. On OpenAI direct, a model's id is its `openai_model_ids` entry or the name without `openai/`, so the configs' `models` block stays identical to the baseline's.
- The token probe uses the method's own prompt and tools with an empty roster (`probe_request`), so roster tokens are measured against the records prompt, not names_only's.
- `diagnostics["candidates"]` is set only when retrieval ran. In `full` mode the order is the roster order, so recall@k would measure nothing.
- An agent the stub creates gets a deterministic id, `ag_` + 8 hex characters from its name, so a later `send_message_to_agent` in the same turn resolves to it.
- Cached purposes are keyed by agent id, prompt + name + first task, and the summarizer model. Fake-model runs use no cache.
- A spend cap reached during an embedding call stops the run instead of falling back to lexical retrieval. A failed embedding call (after retries) falls back, as in production.
- Recall is also reported at k = 8 (the default K), and `report.md` gains a retrieval table in section 7. The mixed-model-version warning now compares versions per requested model, since embedding and backfill calls return other models.

## Open questions

- **Is K = 8 enough** at N = 200 for `implicit_follow_up` and old-thread cases? The probe answers this. If recall@K stays low because the target appears nowhere in the visible history (old-thread cases), that's where the optional `search_agents(query)` tool comes in. It would be a version 1.1 with its own dev run.
- **Does the interaction agent write useful purposes?** Check the first 30 `create_agent` purposes in dev runs by hand. If they're as vague as names, consider the purpose-rewrite option (decision 3's alternative).
- **Position bias in the shown list:** render order is relevance order. If the dev runs show the first shown agent being over-picked, try rendering in `last_active` order instead.
- **Execution results with several agents** pin all of them, up to `max_pinned`. With large parallel batches (phase 2), this could crowd out retrieval. Revisit with phase 2 data.
