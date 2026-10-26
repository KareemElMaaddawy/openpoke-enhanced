# Agent overload: experiment design

The design of the baseline experiment, detailed enough that the harness can be built without making design decisions. It turns the agreed inputs in [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md) into a case format, a harness, scoring rules, metrics and a report. Causes and metric definitions are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md). The problem statement and decision log are in [agent-overload.md](agent-overload.md).

Status: designed 2026-10-25, not implemented. Phase 1 is specified in full. Phases 2 and 3 are outlines.

## Goals and constraints

1. **Baseline numbers** for the current system (names-only roster, full roster in every prompt).
2. **A controlled rerun.** After each improvement the same harness runs again on the same frozen cases, and the report shows whether each metric moved. The routing method can be swapped. Cases, scoring, metrics and the report stay the same.
3. **Reproducible.** The model and provider are pinned, the case set is frozen and hashed, there's a dev/test split, each case is repeated, and the full config is stored with every result.
4. **Lean.** The submission deadline is 2026-10-30, and most of the remaining time belongs to the solution. A full phase 1 run takes about 30 minutes and costs about $8. The user reviews labels for at most about 30 minutes, once.
5. **Budget.** At most **$50 in total** for the whole experiment: fixtures, baselines, iterations and final comparison runs for all phases. The harness enforces it (see [Budget and spend guard](#budget-and-spend-guard)).

## Decisions made while designing

Agreed with the user on 2026-10-25, plus facts checked in the code and on OpenRouter that settle some questions.

| Decision | Choice | Why |
| --- | --- | --- |
| Labels | LLM draft plus a blind second labeler. The user reviews only a short queue (see [Labeling](#labeling-and-review)) | Label quality without hours of review |
| Size | Single-turn: 120 test and 60 dev templates, 2 reps, at all six roster sizes. Sequences: 8 test and 4 dev, 12 turns each, 2 reps per mode, at N = 10, 50, 100, 125, 200 on test and N = 10, 200 on dev | Fits the $50 budget; see [Cost](#cost-and-run-time-estimate). Single-turn cases carry the full scaling curve. Dev results are only a tuning reference, so dev sequences use two sizes |
| Budget | $50 in total, enforced by a per-run cost cap and a spend ledger | Agreed with the user |
| Histories | Long histories are assembled in code from thread exchanges and a chit-chat pool, not written by an LLM | Writing them was the largest fixture cost. A delegated task leaves the same four log entries in production, so assembly is faithful to the format |
| Model | `openai/gpt-6-luna` for every role in `server/config.py`, replacing `anthropic/claude-haiku-5.5` | Haiku 5.5 was a placeholder after Sonnet 4.4 was retired. The user judges gpt-6-luna stronger at this kind of task, so an improvement shown on top of it is more convincing. Same price as Haiku ($0.10 / $0.50 per million tokens). Its prompt-following and tool calling with this system prompt are untested until the smoke run |
| Provider | Pinned to OpenAI on OpenRouter, no fallbacks | Removes provider-to-provider variance between runs. Azure and Bedrock also serve the model |
| Summarization | Kept as it is in production. Sequences start close to the threshold so the real summarizer runs during them. Long single-turn histories carry a real summarizer output | The baseline is the current system, summarization included |
| Temperature | Not set, same as production | The OpenRouter listing for `openai/gpt-6-luna` doesn't accept `temperature` (checked 2026-10-25) |
| Seed | A fixed seed per call position (see [Model calls](#model-calls)) | The model accepts `seed`. Seeding doesn't change what the model can output, only makes a rerun repeat its samples where the provider manages it. OpenAI treats seeds as best effort, so repetitions are still needed |
| Model pin | `openai/gpt-6-luna`, which resolves to `openai/gpt-6-luna-20260922` (checked 2026-10-25). The run aborts if the canonical slug changes | OpenRouter takes only the alias, so the harness checks what the alias points to |
| Agent loop | The harness runs the real `_run_interaction_loop` with tool execution stubbed | Routing turns usually take about 2 model calls (reply and delegate, then finish). Calling the model once would measure a different system |

## Repository layout

Everything lives under `evals/agent_overload/`, a package run from the repo root with `python -m evals.agent_overload.<module>`. It imports `server` but never changes it.

```
evals/
  __init__.py
  agent_overload/
    __init__.py
    configs/
      baseline_names_only.json      # the baseline run config
    fixtures/
      v1/                           # one directory per frozen case-set version, never edited after freezing
        threads.dev.jsonl
        threads.test.jsonl
        agents.dev.jsonl
        agents.test.jsonl
        rosters.dev.json
        rosters.test.json
        cases.single.dev.jsonl
        cases.single.test.jsonl
        cases.sequence.dev.jsonl
        cases.sequence.test.jsonl
        chitchat.jsonl              # small-talk exchanges used to assemble long histories
        review/                     # labeling queue, decisions, and the second labeler's raw outputs
        MANIFEST.json               # file hashes, case_set_hash, generator provenance
    generation/                     # one-off scripts that built the fixtures; not run during experiments
      prompts/                      # generator and labeler prompts, hashed into MANIFEST.json
      gen_threads.py
      name_agents.py
      rate_names.py
      draft_cases.py
      draft_sequences.py
      assemble_histories.py
      summarize_histories.py
      cross_label.py
      build_review.py
      freeze.py
    harness/
      config.py                     # load and validate config, build the recorded config
      llm.py                        # pinned OpenRouter client with usage capture and retries
      fixtures.py                   # load fixtures and verify MANIFEST hashes
      rosters.py                    # build the roster for (case, N)
      state.py                      # AgentView, Entry, RoutingState, transcript rendering, summarization
      methods/
        base.py                     # RoutingMethod protocol, RoutingInput, RoutingOutput
        names_only.py               # baseline: production prompt, full roster, real loop
      runner.py                     # suites: single, sequence, token_probe
      scoring.py                    # outcome labels and tags
      metrics.py                    # aggregation and bootstrap CIs
      report.py                     # report.md from metrics.json
    run.py                          # CLI: run a config
    compare.py                      # CLI: paired comparison of two runs
    tests/                          # unittest only, no new dependencies, no API calls
    results/
      <run_id>/                     # see Results format
      test_ledger.jsonl             # every run on the test split
      spend_ledger.jsonl            # actual cost of every run and fixture step, for the $50 cap
```

Add `evals/agent_overload/results/*/raw/` to `.gitignore`. Everything else in `results/` is committed.

No new dependencies. Configs are JSON, tests use `unittest`, and similarity uses `difflib`.

## Routing-method interface

The only part that changes between experiments. The harness owns the state, the cases, scoring and the report. A method sees what the system would see, and nothing that reveals labels.

```python
# harness/methods/base.py
@dataclass(frozen=True)
class WorkItem:
    instructions: str
    result: str

@dataclass(frozen=True)
class AgentView:
    agent_id: str               # stable harness id; methods that route by id use it
    name: str
    work_log: tuple[WorkItem, ...]   # what this agent has done; names_only ignores it
    created_at: str             # "YYYY-MM-DD HH:MM:SS"; names_only ignores it
    last_active: str            # last delegation to this agent; names_only ignores it
    # deliberately no thread_id

@dataclass(frozen=True)
class Entry:
    tag: str                    # user_message | agent_message | poke_reply | wait
    timestamp: str              # "YYYY-MM-DD HH:MM:SS"
    payload: str

@dataclass(frozen=True)
class RoutingInput:
    roster: tuple[AgentView, ...]    # in roster order
    summary_text: str                # "" when there is no summary
    entries: tuple[Entry, ...]       # unsummarized entries, oldest first
    message_text: str
    message_type: str                # "user" | "agent"

@dataclass
class Delegation:
    agent_key: str              # existing agent_id, or "new:<exact name>"
    agent_name: str             # the name the method used
    instructions: str
    iteration: int              # loop iteration it came from
    order: int                  # order across the whole turn

@dataclass
class RoutingOutput:
    delegations: list[Delegation]
    history_effects: list[Entry]     # poke_reply / wait entries the turn produced, in order
    invalid_calls: list[dict]        # {"tool", "raw_arguments", "error"}
    llm_calls: list["CallRecord"]    # every model call the method made
    diagnostics: dict                # e.g. {"candidates": [...]} for recall@k, {"excluded": [...]} for hidden agents
    loop_limit_hit: bool = False

class RoutingMethod(Protocol):
    name: str
    version: str
    def describe(self) -> dict: ...                       # params, prompt hashes; stored in config
    async def prepare(self, agents: list[AgentView]) -> None: ...   # build records/indices; may cache
    async def route(self, inp: RoutingInput) -> RoutingOutput: ...
```

Rules for every method:

- A method may make any number of model calls. All of them go through `harness/llm.py`, so cost and latency are counted for every method in the same way, guardrails included.
- A created agent is `agent_key = "new:<name>"`. A second call in the same turn with the same new name gets the same key, just as `send_message_to_agent` reuses an agent added a moment earlier.
- A method that asks the user instead of routing returns no delegations and a `poke_reply`. It's scored as `missed_delegation` with the tag `reply_is_question` (see [Tags](#tags)).
- A method that derives records from `work_log` (for example an LLM-written purpose) caches them under `evals/agent_overload/cache/<method>/<version>/`. The cache file's hash is recorded in the run config. Its output is part of the method under test, not part of the case set.
- A retrieval method puts its candidate ids in `diagnostics["candidates"]`, in rank order, so the harness can compute recall@k.
- A method that hides agents from the routing decision (archiving, retrieval) lists them in `diagnostics["excluded"]`. That lets the scorer tag errors caused by hiding the right agent (`target_excluded`) and report how many agents were shown per turn.
- A method's own state, such as archive status, is derived from the `AgentView` fields on each call (for example, archived means `last_active` older than D days before the message). The harness keeps `last_active` current; methods don't store state between turns.

### The baseline method: `names_only` version 1

It reproduces production exactly.

1. **Roster.** `server.agents.interaction_agent.agent.get_agent_roster` is replaced once at harness start-up with a function that returns a fake roster read from a `contextvars.ContextVar`. Each turn sets the variable to its roster's names, so concurrent turns never see each other's rosters. The fake has `load()` (no-op) and `get_agents()`.
2. **Prompt.** `build_system_prompt()` and `prepare_message_with_history(message_text, transcript, message_type)` are called unchanged. The roster names are `[a.name for a in inp.roster]`. `transcript` is `state.render_transcript(inp.summary_text, inp.entries)` (see [Transcript rendering](#transcript-rendering)).
3. **Loop.** A subclass of `InteractionAgentRuntime` overrides two methods:
   - `_make_llm_call` calls `harness/llm.py` with the same payload production sends, plus provider pinning (see [Model calls](#model-calls)).
   - `_execute_tool` dispatches to stub functions that have **the same signatures** as the real tools in `server/agents/interaction_agent/tools.py`. It calls them with `**args` exactly as `handle_tool_call` does, so missing or unexpected arguments fail the same way. The stubs return the same `ToolResult` payloads as the real tools and never touch the roster, the logs or the event loop:
     - `send_message_to_agent`: `{"status": "submitted", "agent_name": name, "new_agent_created": is_new}`. `is_new` is checked against the turn's roster plus names created earlier in the same turn. Records a `Delegation`.
     - `send_message_to_user`: `{"status": "delivered"}`, `user_message=message`. Records a `poke_reply`.
     - `send_draft`: `{"status": "draft_recorded", "to", "subject"}`. Records a `poke_reply` with the text `f"To: {to}\nSubject: {subject}\n\n{body}"`.
     - `wait`: `{"status": "waiting", "reason"}`. Records a `wait`.
     - Unknown tool, invalid JSON or a `TypeError`: the same error payloads as `handle_tool_call`. Recorded in `invalid_calls`.
4. **Run.** The harness calls `runtime._run_interaction_loop(system_prompt, messages)` directly, never `execute()` or `handle_agent_message()`, because those write to the real conversation log. If the loop returns with no `send_message_to_user` and has assistant text, that text is recorded as a `poke_reply`, the same as `_finalize_response` plus `record_reply`. A `RuntimeError` from the 8-iteration limit sets `loop_limit_hit`. Delegations made before the limit are still scored.
5. **Agent keys.** A delegation's `agent_name` is resolved by exact string match against the roster (giving `agent_id`), or against names created earlier in the turn (giving `new:<name>`). An empty `agent_name` is an `invalid_call`. Production would create an agent named `""`.

Importing `server` creates files under `server/data/` if they're missing, which is harmless. The stubs mean the harness never writes to the roster, the conversation log or the execution logs. A test checks this.

## Transcript rendering

The harness keeps the conversation state in memory and renders it the way production does.

- **State:** `summary_text`, `last_index` (index of the last summarized entry, -1 if none), and the full list of `Entry` with global indices.
- **Rendering:** create a `WorkingMemoryLog` at a temp path once, then call `render_transcript(SummaryState(summary_text, last_index, None, unsummarized))`. This is the same function `_load_conversation_transcript` uses while summarization is on (the default).
- **Summarization:** after appending a turn's entries, apply `summarize_conversation`'s rule. If the unsummarized entries number at least `conversation_summary_threshold + conversation_summary_tail_size` (100 + 10 from `get_settings()`), summarize the first 100 with the real `build_summarization_prompt(summary_text, batch)` and the summarizer model, then set `last_index` to the last entry in the batch. The call goes through `harness/llm.py` and is counted.
- **One deviation:** production runs summarization in the background, so the next turn may or may not see the new summary. The harness runs it synchronously before the next turn, which matches production when summarization finishes between messages.
- **Timestamps** are fixed in the fixtures, so renders are deterministic.

Execution results are rendered with the real `ExecutionBatchManager()._format_batch_payload([...ExecutionResult])`, giving `[SUCCESS] <agent_name>: <text>` lines joined by newlines.

## Model calls

`harness/llm.py` builds the production payload (`model`, `messages` with the system prompt first via `openrouter_client.client._build_messages`, `stream: false`, `tools`) and adds only:

```json
{"provider": {"order": ["openai"], "allow_fallbacks": false}, "usage": {"include": true}, "seed": 123456789}
```

- **Seed:** `int(sha256(f"{purpose}|{case_id}|{N}|{mode}|{rep}|{turn}|{iteration}").hexdigest()[:8], 16)`, with `-` for fields that don't apply. A given call position gets the same seed across runs and methods, and different repetitions get different seeds.
- **Provider check:** OpenRouter also lists `openai/flex` and `openai/fast` endpoints for this model, at different prices. The smoke run checks that `order: ["openai"]` lands on the standard endpoint (the returned `provider` and the cost per token). If it doesn't, the config pins the standard endpoint explicitly before any real run.
- **Reasoning:** the model supports reasoning, and production sends no reasoning parameters, so neither does the harness. Reasoning tokens are billed as output and are recorded from `usage.completion_tokens_details.reasoning_tokens`.

- **Timeout:** 60 seconds, as in production.
- **Retries:** up to 5 times with exponential backoff (1, 2, 4, 8, 16 seconds) on HTTP 429, 5xx and network errors. A call that still fails marks the turn `api_error`. That turn is left out of the metrics and counted in the report. The run fails if more than 2% of turns are `api_error`.
- **Pin check:** at start-up, read `GET https://openrouter.ai/api/v1/models`, find the configured model, and compare its `canonical_slug` with `expected_canonical_slug` in the config. If they differ, abort, unless `--accept-model-change` is passed, in which case the report says so in its first line.
- **Per-call `CallRecord`:** `call_id`, `purpose` (`routing` | `summarizer` | `token_probe` | method-specific), the sha256 of the canonical request JSON, the `seed`, the response `id`, the returned `model`, `provider` and `system_fingerprint` (if present), `usage.prompt_tokens`, `usage.completion_tokens`, reasoning tokens, `usage.cost`, cached tokens if reported, `finish_reason`, latency in ms, attempt count, and the path of the raw response in `raw/`.
- **Parity test:** the payload without the two added keys equals what `request_chat_completion` would send for the same inputs.

## Fixtures

One frozen, versioned set (`fixtures/v1/`). Fixtures are generated once by the scripts in `generation/`, reviewed, then frozen. Rerunning an experiment never regenerates them. Changing anything means a new version directory and a new hash.

### World model

Everything is built from **threads**. A thread is one unit of real work (the October AWS invoice, the offsite thread with Keith, the Friday gym reminder). Labels point at threads, and agents belong to threads.

Each split has its own threads. Dev and test share nothing: no threads, no agents, no filler.

**`threads.<split>.jsonl`**, one per line:

```json
{
  "thread_id": "t-test-0042",
  "split": "test",
  "role": "case",
  "category": "finance",
  "topic": "AWS October invoice",
  "opening_request": "can you find my AWS invoice for October?",
  "canned_result": "Found the October AWS invoice: $412.37, due Nov 3, from aws-billing@amazon.com.",
  "result_reply": "Found it: $412.37, due Nov 3.",
  "follow_ups": [
    {"request": "was that paid already?", "result": "No payment recorded for the October invoice yet.", "reply": "Not paid yet."}
  ],
  "near_distractor_of": "t-test-0043"
}
```

- `role` is `case` (used by cases) or `filler` (only fills rosters).
- `follow_ups`: 3 per case thread (none for filler), used to assemble long histories.
- `near_distractor_of` links pairs such as Uber rides and Uber Eats. Both threads in a pair are always in the same split.
- Categories (about equal shares): finance and receipts, travel, work email threads with named people, scheduling and reminders (trigger work), shopping and deliveries, job search, subscriptions and newsletters, family and personal, events and tickets, home and utilities, health and appointments, accounts and security notices. Every topic is something found or done through email, per the no-new-integrations decision.

**Counts per split:**

| Split | Case threads | Filler threads |
| --- | --- | --- |
| test | about 110 (including about 30 near-distractor pairs) | 210 |
| dev | about 55 (including about 15 pairs) | 210 |

Each split has 210 filler threads, so 200 remain after the similarity cleaning below.

**`agents.<split>.jsonl`:** one seeded agent per thread that starts with an agent:

```json
{
  "agent_id": "a-test-0042",
  "thread_id": "t-test-0042",
  "name": "AWS Invoice Lookup",
  "descriptiveness": "specific",
  "seeded": true,
  "work_log": [{"instructions": "Find the user's AWS invoice for October 2026.", "result": "Found the October AWS invoice: $412.37 ..."}],
  "name_source": {"model": "openai/gpt-6-luna", "canonical_slug": "openai/gpt-6-luna-20260922", "attempts": 1, "request_sha256": "..."}
}
```

Threads that a sequence creates during the run also get a name in this file (the gold name for corrected-each-turn runs), with `"seeded": false`.

**`rosters.<split>.json`:** `{"filler_order": ["a-test-0201", ...], "filler_age_days": {"a-test-0201": 23.4, ...}}`. `filler_order` is a fixed order of the filler agents, shuffled once at generation with seed `20261025`.

**Agent ages.** Archiving needs to know how long ago each agent was used. Ages are stored relative to the case's "now", the timestamp of the case's message (single-turn) or of the first turn (sequences). The harness turns them into `last_active` and `created_at`:

- **Filler agents:** `filler_age_days`, drawn once with seed `20261025`. 30% are 0 to 3 days old, 30% are 4 to 14 days, and 40% are 15 to 60 days, so most of a large roster is dormant, as it would be after weeks of use.
- **Required agents named in the case's history** (including the summarized part): `last_active` is the timestamp of the latest result line with their name. `freeze.py` computes this.
- **Other required agents:** the case's `agent_ages` field.
- **`created_at`:** `last_active` minus a seeded 0 to 30 days, and never after the agent's first result line.

### Generating agent names (open question 1)

Names have to look like names the interaction agent itself writes, so the interaction agent writes them.

1. `gen_threads.py`: `anthropic/claude-sonnet-5.5` generates thread specs in batches of 25 per category from a fixed prompt in `generation/prompts/`. It's told the existing topics so it doesn't repeat them, and to create the near-distractor pairs explicitly.
2. `name_agents.py`: for each thread, run the **real** interaction prompt (the pinned interaction model and provider, empty roster, empty history) with `opening_request` as `<new_user_message>`, through the `names_only` loop. Take the `agent_name` of the first `send_message_to_agent`. If there's no delegation, retry, up to 3 attempts. If the name exactly matches or slug-collides with a name already taken in the split, resample, up to 3 attempts, then drop the thread. Record attempts.
3. `rate_names.py`: Sonnet 5.5 rates each name against its thread topic as `specific` (names the entity and the task), `partial` (one of the two) or `generic` (neither, for example "Email Helper"). Whatever mix comes out is the natural mix and is reported, not forced.
4. **Filler cleaning:** drop any filler agent whose name is similar to a case thread's agent name in the same split (`difflib.SequenceMatcher` ratio of the slugs ≥ 0.6, or shared non-stopword tokens ≥ 2), so filler can't make a label ambiguous. Trim to exactly 200 filler agents per split.

### Building the roster for (case, N)

`harness/rosters.py`, deterministic and the same for every method and repetition:

1. `required` = the case's `required_agents`: the target agents, their near-distractors, and every agent named in the case's history.
2. `filler` = the first `N - len(required)` ids of `filler_order`. Rosters are nested: the filler at size N is a prefix of the filler at any larger size.
3. Random generator: `random.Random(int(sha256(f"{case_id}|{N}|roster").hexdigest()[:16], 16))`.
4. Place the **position anchor** (the first target thread's agent; for CREATE and NO_DELEGATION, the near-distractor if there is one) in its `target_position` bucket. The buckets are `first_third` `[0, N//3)`, `middle_third` `[N//3, 2N//3)` and `last_third` `[2N//3, N)`, and the index within the bucket is drawn with the generator above. Shuffle the remaining agents into the other slots with the same generator.
5. In sequences, agents created during the run are appended at the end, the same as `roster.add_agent`.

Constraint for case authors: `len(required) ≤ 6` for single-turn cases and `≤ 8` for sequences, so N=10 still contains filler.

### Single-turn case format

**`cases.single.<split>.jsonl`:**

```json
{
  "case_id": "s-test-0007",
  "split": "test",
  "required_agents": ["a-test-0042", "a-test-0043", "a-test-0050"],
  "target_position": "last_third",
  "history": {
    "type": "short",
    "summary_text": "",
    "last_index": -1,
    "entries": [
      {"tag": "user_message", "timestamp": "2026-10-20 09:14:00", "payload": "can you find my AWS invoice for October?"},
      {"tag": "poke_reply", "timestamp": "2026-10-20 09:14:05", "payload": "on it"},
      {"tag": "agent_message", "timestamp": "2026-10-20 09:15:10", "payload": "[SUCCESS] AWS Invoice Lookup: Found the October AWS invoice: $412.37 ..."},
      {"tag": "poke_reply", "timestamp": "2026-10-20 09:15:15", "payload": "Found it: $412.37, due Nov 3."}
    ]
  },
  "message": {"type": "user", "subtype": "user", "text": "forward that to my accountant"},
  "label": {"kind": "REUSE", "threads": ["t-test-0042"]},
  "meta": {
    "query_style": "implicit_follow_up",
    "prev_thread": "t-test-0042",
    "name_descriptiveness": "specific",
    "target_name_visible": true,
    "target_age_bucket": "recent"
  },
  "agent_ages": {"a-test-0050": 9.0},
  "provenance": {"drafted_by": "anthropic/claude-sonnet-5.5", "cross_label": {"model": "google/gemini-3.8-flash", "label": {"kind": "REUSE", "threads": ["t-test-0042"]}, "agreed": true}, "review": null}
}
```

- **`history.type`:** `short` (4 to 16 entries, no summary) or `summarized`.
  - The drafter writes only the **relevant tail** of a case, the last 4 to 16 entries.
  - For a `summarized` case, `assemble_histories.py` puts 100 to 126 assembled entries in front of the tail (see [Assembling long histories](#assembling-long-histories)), so the raw history has at least 110 entries.
  - `summarize_histories.py` then applies the production rule once with the real summarizer (the pinned summarizer model). The fixture stores the result: `summary_text`, `last_index`, and the remaining entries (at least 10, always including the drafted tail).
  - The raw history is kept in `review/raw_histories/<case_id>.jsonl` for audit and is not used at run time.
  - Summarized histories are what a user with a large roster has in production.
- **`label.kind`:** `REUSE` (exactly one thread), `REUSE_ANY` (two or more threads), `CREATE` (the label also carries `new_thread`, the thread the new work belongs to), or `NO_DELEGATION`.
- **`message.type`:** `user` or `agent`. `message.subtype` is `user`, `execution_result` (text in batch-payload format) or `email_alert` (text starting `Important email watcher notification:\n`, as `importance_watcher.py` sends it).
- **`meta.prev_thread`:** the thread of the most recent result line in the visible history, or `null`. Used for recency lock.
- **`meta.target_name_visible`:** whether any target agent's exact name appears in the rendered transcript. Computed by `freeze.py`, not written by the drafter.
- **`meta.target_age_bucket`:** `recent` (target agent last active 0 to 3 days before the message), `mid` (4 to 14 days) or `old` (15 to 60 days). Computed by `freeze.py` from the agent ages. `null` for CREATE and NO_DELEGATION.
- **`agent_ages`:** age in days for each required agent not named in the history. Required for old-thread cases.

**Quotas for single-turn templates:**

| Label | Query style | Test | Dev |
| --- | --- | --- | --- |
| REUSE | explicit | 18 | 9 |
| REUSE | paraphrased | 18 | 9 |
| REUSE | implicit_follow_up | 18 | 9 |
| REUSE | near_distractor | 18 | 9 |
| REUSE_ANY | any | 10 | 5 |
| CREATE | plain | 14 | 7 |
| CREATE | near_distractor | 12 | 6 |
| NO_DELEGATION | any | 12 | 6 |
| **Total** | | **120** | **60** |

Cross-quotas within each split:

- **History:** 70% `short`, 30% `summarized`.
- **Message type:** about 80% user, 10% `execution_result`, 10% `email_alert`. Agent messages fall mostly in NO_DELEGATION, and partly in REUSE where the result asks for follow-up work.
- **Target position:** balanced across the three buckets within each query style.
- **Old-thread cases:** 11 test cases (6 of the REUSE `explicit` and 5 of the REUSE `near_distractor`) and 6 dev cases (3 and 3). In each, the user returns to a thread whose agent was last active 15 to 60 days earlier. The thread doesn't appear in the visible history, so the agent's name is the only clue under names-only routing. That's why these cases use only `explicit` and `near_distractor` styles, so the labeling rule that T must be identifiable still holds. These are the cases where archiving can fail by hiding the right agent.

**Query styles:**

- `explicit`: names the topic in words close to the agent name.
- `paraphrased`: same thread, little word overlap with the agent name.
- `implicit_follow_up`: points at earlier work ("reply to that", "move it to Friday") and can only be resolved through the history.
- `near_distractor`: the roster holds a similar thread's agent. A REUSE label points at the right member of the pair. A CREATE label means only the wrong member exists.

### Sequence case format

**`cases.sequence.<split>.jsonl`:**

```json
{
  "case_id": "q-test-003",
  "split": "test",
  "required_agents": ["a-test-0060", "a-test-0061", "a-test-0070", "a-test-0071"],
  "initial_history": {"summary_text": "", "last_index": -1, "entries": ["... 96 entries ..."]},
  "turns": [
    {
      "turn": 1,
      "timestamp": "2026-10-21 08:02:00",
      "message": {"type": "user", "subtype": "user", "text": "did the uber eats refund come through?"},
      "label": {"kind": "REUSE", "threads": ["t-test-0061"]},
      "meta": {"query_style": "near_distractor", "primary_thread": "t-test-0061"},
      "gold": {
        "create_name": null,
        "poke_replies": ["checking"],
        "result_text": "Refund of $18.40 from Uber Eats posted Oct 20.",
        "result_reply": "Yep, $18.40 landed Oct 20."
      }
    }
  ]
}
```

- **Initial history:** 96 raw entries of earlier conversation about the seeded threads, with proper result lines, built by `assemble_histories.py`. Each turn adds about 4 entries, so the 110-entry threshold is crossed around turn 4 and the real summarizer runs once per sequence-run.
- **`agent_ages`:** as in single-turn cases, for required agents not named in the initial history, relative to the first turn's timestamp.
- **Turn mix in each 12-turn sequence:** 2 CREATE (new threads that later turns reuse), 6 REUSE (at least one `implicit_follow_up` right after a topic switch, and at least one `near_distractor`), 1 REUSE_ANY, 2 NO_DELEGATION, and 1 more of any label. At least one turn is an `email_alert`.
- **Topic switches:** at least half of the delegating turns switch thread from the previous delegating turn, so recency lock can be measured.
- **`meta.primary_thread`:** the thread a delegation on this turn is attributed to. For CREATE it's the new thread. For REUSE_ANY it's the first listed thread. For NO_DELEGATION it's the thread under discussion, or `null`.
- **`gold`:** what the correct system would add to the history. `create_name` is the frozen name from `agents.<split>.jsonl` for CREATE turns.

### Assembling long histories

`assemble_histories.py` builds long histories in code. It's deterministic, with a generator seeded by `sha256(f"{case_id}|history")`, and makes no model calls.

- **Exchanges.** A history is a series of exchanges, the same shapes production logs:
  - **Delegated exchange (4 entries):** `user_message` (the thread's `opening_request` or one of its `follow_ups[].request`), `poke_reply` (an acknowledgement from the chit-chat pool's ack list), `agent_message` (`[SUCCESS] <agent name>: <result>` via `_format_batch_payload`), and `poke_reply` (`result_reply` or `follow_ups[].reply`).
  - **Chit-chat exchange (2 entries):** a `user_message` and a `poke_reply` from `chitchat.jsonl`. These are NO_DELEGATION small talk and questions answered directly.
- **Which threads.** Only the case's `required_agents` and their threads appear in delegated exchanges. Every agent named in a history is therefore in the roster at every N, as it would be in production, where agents are never removed. Roster size is then the only thing that changes between sizes.
- **Mix.** About 60% delegated and 40% chit-chat exchanges. Each required thread starts with its opening request before any follow-up.
- **Timestamps:** spread over the 3 days before the drafted tail, 08:00 to 22:00, at least 2 minutes apart.
- **`chitchat.jsonl`:** about 60 exchanges and 15 acknowledgements, drafted once by Sonnet 5.5 and reviewed by the implementing agent.

### Labeling and review

The goal is trustworthy labels with no more than about 30 minutes of the user's time.

**Labeling rules** (the drafter and the second labeler get the same text, stored in `generation/prompts/labeling_rules.md`):

1. REUSE(T): the message continues T's work, acting on what T found or made or following up on T's email or trigger, and T is identifiable from what the model sees (a result line, the summary, or an unambiguous name). If T isn't identifiable, don't write the case.
2. REUSE_ANY: two or more agents visibly hold enough context, for example two agents that both reported the same email.
3. CREATE: the work isn't covered by any agent's visible work. Don't write cases where "a new agent in parallel" is equally valid. Those belong to phase 2.
4. NO_DELEGATION: answerable from visible context, small talk, or an agent message that only needs summarizing for the user.
5. Don't write cases where asking the user is the only sensible response.

**Process:**

1. `draft_cases.py` and `draft_sequences.py`: Sonnet 5.5 drafts cases to fill the quotas, with the frozen agent names in hand. It writes messages, labels, meta, short histories and the relevant tails. Long histories are assembled afterwards (see [Assembling long histories](#assembling-long-histories)). A schema check rejects malformed drafts and they're redrafted.
2. `cross_label.py`: `google/gemini-3.8-flash` (canonical `google/gemini-3.8-flash-20260902`) sees the labeling rules and exactly what the interaction agent would see at **N=200** (the largest roster, so any filler that could be a valid target gets a chance to show up), and returns a label without seeing the draft's. Sequences are labeled turn by turn from the gold state. The labeler comes from a different family than both the drafter (Anthropic) and the system under test (OpenAI). That makes its errors less correlated with the drafter's, and keeps labels from drifting toward what the system under test would do.
3. `build_review.py`: agreed labels are accepted. For each disagreement, the implementing agent applies the labeling rules and writes a one-line rationale: it fixes the label, rewrites the case to remove the ambiguity, or marks it **unsure**. The user's queue, `review/review_sheet.md`, holds only the unsure items plus 10 random agreed items as a sanity check. Each item shows the message, the visible history tail, the relevant roster entries and both labels.
4. **Time cap:** if the queue has more than 30 items, the most ambiguous items are dropped and replaced by fresh drafts, which repeat steps 1 to 3, instead of spending more review time. If more than 1 of the 10 sanity items is wrong, the user and the agent review a further 20 agreed items together before freezing.
5. Every decision is stored in `provenance.review`: `{"by": "agent" | "user", "note": "..."}`.

### Freezing and the case-set hash

`freeze.py`:

1. Validates every file against the schemas above and computes `meta.target_name_visible`.
2. Writes `MANIFEST.json` with `case_set_version`, the per-file sha256, the sha256 of every generator prompt, the generator models with their canonical slugs, the count of each quota cell, and
   `case_set_hash = sha256("".join(f"{path}\0{sha256(file)}\n" for path in sorted(fixture_files)))`.

The harness verifies every hash at load and refuses to run on a mismatch.

### Dev/test discipline

- Tuning a later method (prompts, thresholds, k, weights) uses only `dev`.
- Every run that includes `test` appends a line to `results/test_ledger.jsonl`: `{"run_id", "method", "method_version", "config_hash", "case_set_hash", "date"}`.
- `run.py` refuses a second test run for the same `method` and `method_version` with a different config hash. Changing a method means bumping its version, so the ledger shows how many test runs each idea got.
- The baseline has nothing to tune, so it runs on both splits. Test is the headline. Dev numbers are the reference for tuning later methods.

## Run modes

### Suites

| Suite | Unit | What happens |
| --- | --- | --- |
| `single` | (case, N, rep) | Build the state from the fixture, run the method once, score |
| `sequence` | (sequence, N, mode, rep) | Play the turns in order, update the state after each turn (below), score each turn, then score the end state |
| `token_probe` | (case) | One call with an empty roster (`max_tokens: 1`) on the first-iteration prompt of each single-turn case, for roster-token deltas |

### State update between sequence turns

After turn t, before scoring is used for anything:

**Carried forward** (the model's choices stick):

1. Append `user_message` (or `agent_message` for agent turns) at the turn's timestamp.
2. Append `history_effects` (the method's replies and waits) at timestamp +5 s, +6 s, and so on.
3. For each distinct `agent_key`: if it's new, add an agent to the roster at the end, with a fresh id `a-run-<n>` and the method's name, and map it to the turn's `primary_thread` (or to `orphan` if that's `null`). Add `WorkItem(instructions, result)` to its work log. Set its `last_active` to the turn's timestamp, and `created_at` too if it's new.
4. If there were delegations, append one `agent_message` at +60 s from `_format_batch_payload`. There's one `[SUCCESS] <agent_name used>: <text>` line per distinct agent. The text is `gold.result_text` for the primary delegation and `Done.` for any other.
5. If there were delegations, append `gold.result_reply` as a `poke_reply` at +65 s. This stands in for the interaction agent's turn on the result, which the harness doesn't run, to save cost and keep runs comparable.
6. Apply the summarization rule.

**Corrected each turn:** after scoring, replace the state with the gold state. That's the initial state plus, for every turn up to t: the message, `gold.poke_replies`, the gold agent for the label (the existing agent for REUSE, the first listed thread's agent for REUSE_ANY, a new agent named `gold.create_name` for CREATE), the result line with that agent's name, and `gold.result_reply`. Summarization runs on the gold entries in the same way.

The harness keeps two maps:

- **`agent_thread`:** each agent's creation thread. Seeded agents are mapped from the fixture. A created agent maps to the `primary_thread` of the turn that created it.
- **`agent_context`:** every thread an agent has been given work for. Used only for the `context_reuse` tag.

The **canonical agent** of a thread is the first agent mapped to it, whether seeded or created.

## Scoring

`harness/scoring.py`, version 1. It works the same way for every method.

### Per turn

Inputs: the label, the roster snapshot at the start of the turn, the `agent_thread` map, `prev_thread`, and the method's `RoutingOutput`.

1. Each item in `invalid_calls` gets the outcome `invalid_call`.
2. Collapse delegations with the same `agent_key` into one, and keep the count as `repeat_calls`. Let D be the distinct delegations in order.
3. **NO_DELEGATION label:**
   - If D is empty: `correct_no_delegation`.
   - Otherwise every delegation gets `extra_delegation`.
4. **Delegating label** (REUSE, REUSE_ANY or CREATE):
   - If D is empty: `missed_delegation`.
   - Otherwise the **primary** is the first delegation in D whose classification below is `correct_*`, or the first in D if none is. Every other delegation gets `extra_delegation`.
5. **Classify the primary:**

| Label | Primary targets an existing agent `a` with `t = agent_thread[a]` | Primary creates a new agent |
| --- | --- | --- |
| REUSE(T) | `t == T` and `a` is canonical: `correct_reuse`. `t == T`, not canonical: `duplicate_reuse`. Otherwise: `misroute` | `false_spawn` |
| REUSE_ANY(Ts) | `t in Ts` and canonical: `correct_reuse`. `t in Ts`, not canonical: `duplicate_reuse`. Otherwise: `misroute` | `false_spawn` |
| CREATE | `false_reuse` | `correct_create` |

6. **Turn result:**
   - `turn_correct` is true only when the primary outcome is `correct_reuse`, `correct_create` or `correct_no_delegation` and there's no `extra_delegation`.
   - `turn_correct_lenient` also accepts `duplicate_reuse`.
   - `invalid_call` doesn't by itself make a turn wrong (the model may retry within the loop). It's reported as its own rate.
7. **Status:**
   - `api_error` turns are left out of the metrics.
   - `loop_limit_hit` turns are scored on what they did before the limit and are counted.

`correct_no_delegation` and the `api_error` status are additions to the agreed outcome table, which had no label for a correct NO_DELEGATION. Every other outcome is as agreed.

### Tags

Tags are added to outcomes. They never change them.

| Tag | On | Rule |
| --- | --- | --- |
| `near_duplicate` | `false_spawn` | `slug(new)` vs `slug(e)` for every agent `e` of the expected threads: `SequenceMatcher` ratio ≥ 0.75, or token Jaccard ≥ 0.5 (tokens split on `-`, stopwords removed: to, for, the, a, an, of, and, with, my, re), or equal slugs |
| `slug_collision` | any created agent | `slug(new) == slug(e)` for any roster agent `e` with `new != e`. Production would share one log file (cause I4). Uses `_slugify` from `log_store.py` |
| `recency` | `misroute`, `false_reuse` | the chosen agent's thread equals `prev_thread` and differs from the expected thread |
| `context_reuse` | `misroute` | the chosen agent's `agent_context` contains the expected thread (sequences only; shows when strict scoring might be harsh) |
| `reply_is_question` | `missed_delegation` | the last `poke_reply` of the turn ends with `?`. A heuristic, reported as such |
| `target_excluded` | `false_spawn`, `misroute`, `missed_delegation` | the canonical agent of every expected thread is in the method's `diagnostics["excluded"]`. The error happened because the method hid the right agent (archived it, or retrieval missed it) |

### End of sequence (carried forward only)

Let S be the threads the sequence touches (its labels' threads, plus `orphan` if used).

- `agents_in_S` = agents whose `agent_thread` is in S, seeded and created.
- `extra_agents` = Σ over threads in S of max(0, number of agents − 1), plus all `orphan` agents.
- `duplicate_rate` = `extra_agents / agents_in_S`.
- `inflation_ratio` = `agents_in_S` / number of threads in S that have at least one agent.
- `created` = agents created in the run. `gold_created` = the number of CREATE turns.
- `slug_collisions` = created agents tagged `slug_collision`.

## Metrics

`harness/metrics.py` writes `metrics.json`. Every metric is computed per split, per suite (and per mode for sequences), and **per roster size N**. A line marked "all N" pools them.

### Routing (suites `single` and `sequence`)

| Metric | Definition |
| --- | --- |
| Routing accuracy | mean of `turn_correct` over turn-runs. Also the lenient version |
| False spawn rate | `false_spawn` / turns labeled REUSE or REUSE_ANY |
| Misroute rate | `misroute` / turns labeled REUSE or REUSE_ANY |
| False reuse rate | `false_reuse` / turns labeled CREATE |
| Missed delegation rate | `missed_delegation` / delegating labels |
| Extra delegation rate | turns with at least one `extra_delegation` / all turns |
| Invalid call rate | turns with at least one `invalid_call` / all turns |
| Near-duplicate share | share of `false_spawn` tagged `near_duplicate` |
| Recency lock rate | among delegating turns where the expected thread differs from `prev_thread`: share whose primary went to `prev_thread`'s agent. Headline from `sequence` corrected mode |
| Consistency | share of templates where all reps produced the same primary outcome |
| Confusion matrix | rows = label kind, columns = primary outcome, counts |

**Breakdowns** (accuracy plus outcome shares): query style, message subtype, label kind, target position bucket, target age bucket, name descriptiveness, history type, `target_name_visible`, and for sequences the turn index and mode.

**Archiving and roster shown:**

| Metric | Definition |
| --- | --- |
| Agents shown per turn | roster size minus `len(diagnostics["excluded"])`. Median per N. Equals N for the baseline |
| Dormant agent fraction | share of roster agents whose `last_active` is more than 14 days before the turn. A property of the fixtures in single-turn cases, reported per N for reference |
| Excluded-target error rate | turns tagged `target_excluded` / delegating-label turns. Reported overall and for the `old` age bucket |

**Compounding:** accuracy per turn index, carried forward minus corrected each turn, at each N.

**Accuracy drop point** (the "N" for retrieval above N): the smallest N where accuracy is more than 5 percentage points below accuracy at N=10, with the paired bootstrap 95% CI of the difference excluding 0. Single suite, test split.

### Duplicates (sequence suite, carried forward)

Mean and 95% CI over sequence-runs of `duplicate_rate`, `inflation_ratio` and `extra_agents` per thread, plus `created − gold_created`, and the slug-collision count. All per N.

### Tokens and latency

| Metric | Definition |
| --- | --- |
| Roster tokens per call | for each single-turn case: first-iteration `prompt_tokens` at N minus the `token_probe` value at N=0. Median, plus a linear fit against N (tokens per agent) |
| Roster tokens per turn | roster tokens per call × the number of routing calls in the turn, because every loop iteration resends the roster |
| Input tokens per turn | Σ `prompt_tokens` over all of the method's calls in the turn. Median and p95 |
| Cost per turn | Σ `usage.cost`. Mean (guardrail) |
| Interaction agent latency per turn | Σ call latency in the turn. Median and p95. Measured at the configured concurrency, so compare only runs with the same concurrency |
| Calls per turn | mean number of model calls |

Recall@k is reported only when a method fills `diagnostics["candidates"]`: the share of delegating-label turns where an expected thread's agent is in the top k, for k in 1, 3, 5, 10, 20.

### Uncertainty

- **CIs:** 95% cluster bootstrap over templates (sequences for the sequence suite), 2,000 resamples, seed `20261025`. Repetitions stay inside their template.
- **`compare.py`:** pairs runs by template and reports per-metric differences with a paired bootstrap CI, plus a McNemar test on each template's majority outcome (correct or not). It refuses to compare runs whose `case_set_hash` or splits differ. It warns when model canonical slugs, the provider or the harness version differ.
- **Expected precision** on the test split (120 templates, accuracy around 80%):
  - About ±7 points on overall accuracy.
  - About ±18 points per query style.
  - Per-style results show only large effects. Paired comparisons between methods are more sensitive than these widths suggest.

## Results format

`results/<run_id>/`, with `run_id = <UTC yyyymmdd-HHMMSS>-<method>-<config_hash[:8]>`:

| File | Committed | Content |
| --- | --- | --- |
| `config.json` | yes | the input config, plus everything under "Recorded with every run" |
| `turns.jsonl.gz` | yes | one line per turn-run (fields below) |
| `sequences.jsonl.gz` | yes | one line per sequence-run: end-state roster additions, `agent_thread`, end-of-sequence stats |
| `calls.jsonl.gz` | yes | one `CallRecord` per model call |
| `metrics.json` | yes | every metric above, with CIs |
| `report.md` | yes | the human-readable report |
| `raw/` | no | raw request and response JSON per call |

**Fields on each turn line:** `run_id`, `split`, `suite`, `case_id`, `turn` (null for single-turn), `mode`, `N`, `rep`, `method`, `label`, `meta`, the roster index of each required agent, the delegations (`agent_key`, `agent_name`, `instructions`, `iteration`), the history effects, `outcomes`, `primary_outcome`, `tags`, `turn_correct`, `turn_correct_lenient`, `status`, `call_ids`, `prompt_tokens`, `completion_tokens`, `cost`, `latency_ms`.

### Recorded with every run

- The git commit SHA and dirty flag. `run.py` refuses a dirty tree unless `--allow-dirty` is passed, and the report flags it.
- The harness version, scorer version, `case_set_version` and `case_set_hash`.
- The sha256 of `server/agents/interaction_agent/system_prompt.md`, of `json.dumps(TOOL_SCHEMAS, sort_keys=True)`, of the summarizer system prompt, and of the `server/` and `evals/agent_overload/harness/` source trees. The trees are hashed as the sorted list of `path\0sha256(file)` over tracked `.py` and `.md` files.
- The method's `describe()` output and the hashes of any method cache.
- Model ids, the canonical slugs expected and observed, the provider settings, and any extra parameters (none for the baseline).
- The summarization settings (`conversation_summary_threshold`, `conversation_summary_tail_size`) and `MAX_TOOL_ITERATIONS`.
- Concurrency, retries, timeout, roster sizes, reps, modes, splits, seeds and bootstrap settings.
- The Python version, start and end times, and counts of `api_error` and `loop_limit_hit`.

### Report layout (`report.md`)

1. **Run identity:** run id, method, case set, model and provider, git SHA, warnings (dirty tree, model change, error counts).
2. **Headline (test split):** a table with one row per N and the columns accuracy, false spawn, misroute, false reuse, missed delegation, extra delegation, duplicate rate, roster tokens per turn, input tokens per turn, cost per turn and latency p50. Each cell shows the value with its CI. Sequence-only columns (duplicate rate) show `n/a` at N=25, where sequences don't run.
3. **Accuracy drop point.**
4. **Confusion matrices:** at N=10 and N=200.
5. **Breakdown tables:** one per breakdown dimension, rows = N.
6. **Sequences:** carried forward vs corrected each turn, compounding by turn index, recency lock, duplicate stats.
7. **Tokens:** roster tokens against N and the per-agent slope.
8. **Consistency, invalid calls, loop limits.**
9. **Dev split:** the same headline table.
10. **Costs:** total cost and calls by purpose.

### Configs and profiles

`configs/baseline_names_only.json`:

```json
{
  "experiment": "agent_overload",
  "harness_version": "1.0.0",
  "scorer_version": "1",
  "case_set": {"version": "v1", "manifest": "evals/agent_overload/fixtures/v1/MANIFEST.json", "expected_hash": "<filled at freeze>"},
  "method": {"name": "names_only", "version": "1", "params": {}},
  "models": {
    "interaction": "openai/gpt-6-luna",
    "summarizer": "openai/gpt-6-luna",
    "expected_canonical_slugs": {"openai/gpt-6-luna": "openai/gpt-6-luna-20260922"},
    "provider": {"order": ["openai"], "allow_fallbacks": false},
    "seed_policy": "per_call_position",
    "extra_params": {}
  },
  "suites": {
    "single": {"reps": 2, "roster_sizes": {"test": [10, 25, 50, 100, 125, 200], "dev": [10, 25, 50, 100, 125, 200]}},
    "sequence": {"reps": 2, "modes": ["carried", "corrected"], "roster_sizes": {"test": [10, 50, 100, 125, 200], "dev": [10, 200]}},
    "token_probe": {"enabled": true}
  },
  "runtime": {"concurrency": 16, "max_retries": 5, "timeout_s": 60, "max_api_error_rate": 0.02},
  "budget": {"max_cost_usd": 10.0, "total_cap_usd": 50.0, "estimate_margin": 1.25},
  "stats": {"bootstrap_resamples": 2000, "ci": 0.95, "seed": 20261025}
}
```

Profiles on the command line (`run.py --config ... --profile <name>`):

| Profile | Splits | N | Reps | Cases | Use |
| --- | --- | --- | --- | --- | --- |
| `smoke` | dev | 10, 200 | 1 | 10 single, 1 sequence | check the harness end to end before a real run (a few minutes, about $0.15) |
| `dev-quick` | dev | 10, 200 | 1 | all | fast iteration on a later method (about $0.50) |
| `dev` | dev | config | config | all | a fuller check of a later method before its test run (about $2) |
| `test` | test | config | config | all | the comparison run for a finished method version (about $6) |
| `full` | dev, test | config | config | all | the baseline (about $8) |

## Phase 1 implementation order and checks

1. Build `state.py`, `rosters.py`, `scoring.py` and `metrics.py` with unit tests first. None of them need the API.
2. Build `llm.py` and `methods/names_only.py`, then the parity tests.
3. Generate fixtures (`generation/`), run the review, freeze.
4. Run the `smoke` profile. Replace the estimates in [Cost](#cost-and-run-time-estimate) with measured calls per turn and tokens per call.
5. Run the `full` baseline. Record the result in the Experiments section of [agent-overload.md](agent-overload.md).

### Who runs what

The implementing agent builds the code and runs only free steps (unit tests, a fake-model run, reading outputs). **The user runs every command that calls a paid API**, steps 3 to 5 above, by hand from the runbook.

**Safeguards on paid commands** (every generation script and `run.py`):

- **`--dry-run`** prints the planned calls, models, the estimated cost and the ledger total, then exits without calling any API.
- **Without `--confirm-spend`**, a paid command prints the same summary and exits with a non-zero code. The implementing agent never passes this flag.
- With `--confirm-spend`, the [spend guard](#budget-and-spend-guard) still applies.
- **`--fake-model`** swaps every model call for a deterministic fake. It's used by the tests and by the agent's own end-to-end check, and its results are marked fake and refused by `compare.py`.

### Runbook

`docs/agent-overload-experiment-runbook.md`, linked from [docs/README.md](README.md), written by the implementing agent and kept current. It's the document the user follows, and it's also used to present how the experiment is run. For each step:

- the exact command, copy-pasteable, run from the repo root
- what it does, in one or two sentences
- the estimated cost and time, and the `--dry-run` command to check them first
- what it writes and where
- what to check before going on (for example: agreement rate, review queue length, measured cost per turn against the estimate)
- what to do if it fails or is capped

It also covers:

- **Setup:** `make setup`, and a dedicated OpenRouter key with a $50 limit in `.env` or exported in the user's shell.
- **The review step:** how to open `review/review_sheet.md`, how to record decisions, and how to freeze.
- **Reading the report:** where `report.md` is and what each headline column means.
- **Rerunning for a later method:** `--profile test` with the method's config, then `compare.py` against the baseline run id.

**Required tests (`tests/`, unittest, no API calls):**

- **Transcript parity:** entries rendered by the harness equal `ConversationLog.load_transcript()` over the same entries written to a temp file with `_default_formatter`, and equal `WorkingMemoryLog.render_transcript` once a summary is set.
- **Prompt parity:** `names_only` with the contextvar roster gives the same messages as `prepare_message_with_history` backed by a real `AgentRoster` at a temp path with the same names.
- **Stub parity:** each stub returns the same `ToolResult` payload as the real tool, the real one pointed at temp paths.
- **Payload parity:** see [Model calls](#model-calls).
- **Rosters:** deterministic, nested filler, anchor in its bucket at every N, required agents always present.
- **Ages:** `last_active` matches the latest result line for agents named in the history, `created_at` ≤ `last_active`, every `old` case's target is 15 to 60 days old and absent from the visible history, and sequences update `last_active` on delegation.
- **Scorer:** one test per outcome label and per tag, including a duplicate name in the same turn, an empty name, a `TypeError` in the arguments, and the loop limit.
- **No side effects:** a fake-model smoke run leaves every file under `server/data/` unchanged (compare mtimes and hashes before and after).
- **Manifest:** changing one byte of a fixture makes loading fail.

## Cost and run time estimate

These are estimates, to be replaced by the `smoke` run's measurements. Prices are from OpenRouter on 2026-10-25: gpt-6-luna on the standard OpenAI endpoint is $0.10 per million input tokens and $0.50 per million output tokens. That's the same as Haiku 5.5, which these estimates were first made for. The token counts below assumed Claude's tokenizer. The GPT tokenizer usually needs somewhat fewer tokens for English, but any reasoning tokens add to output. Both get measured in the smoke run.

**Assumptions:**

| Item | Estimate | Basis |
| --- | --- | --- |
| Static prompt (system prompt + tool schemas + tool-use overhead) | 3,800 tokens | 10,424 + 2,103 characters at about 3.5 characters per token, plus overhead (guess) |
| Roster | 10 tokens per agent (about 850 to 1,050 on average, depending on the suite's sizes) | `<agent name="AWS Invoice Lookup" />` is 35 characters |
| History | 600 (short), 1,400 (summarized), 3,500 (sequence average) | fixture design |
| Routing calls per turn | 2.2 | reply and delegate, then a finishing call (guess) |
| Output per call | 150 tokens | tool calls plus a short reply |

**Phase 1 per run:**

| Suite | Units | Turns | Input tokens | Cost |
| --- | --- | --- | --- | --- |
| single, test | 120 × 6 N × 2 reps | 1,440 | 17M | $2.0 |
| single, dev | 60 × 6 N × 2 reps | 720 | 9M | $1.0 |
| sequence, test | 8 × 12 turns × 5 N × 2 modes × 2 reps | 1,920 | 35M | $3.8 |
| sequence, dev | 4 × 12 turns × 2 N × 2 modes × 2 reps | 384 | 7M | $0.8 |
| summarizer | 192 sequence-runs × 1 | | 1M | $0.2 |
| token probe | 180 × 1 | | 1M | $0.1 |
| **Total (`full`)** | | **4,464** | **about 70M** | **about $8** |

Costs include output, at about 330 tokens per turn.

- **Model calls:** about 10,000 for a `full` run.
- **Run time:** about 30 minutes at concurrency 16 and about 2.5 s per call (guess). A sequence-run is a serial chain of about 75 s, and the 192 chains run in parallel.
- **Profiles:**

  | Profile | Time | Cost |
  | --- | --- | --- |
  | `test` | about 20 minutes | about $6 |
  | `dev` | about 8 minutes | about $2 |
  | `dev-quick` | a few minutes | about $0.50 |
  | `smoke` | a few minutes | about $0.15 |

**One-off phase 1 fixture generation: about $8.**

- **Sonnet 5.5, about $5 (a guess).** It writes:
  - about 565 thread specs, with follow-ups for the case threads
  - 180 single-turn cases with short histories or tails
  - 12 sequences
  - name ratings
  - the chit-chat pool
  - about 20% redrafts
- **Gemini 3.8 Flash second labeler, about $2.50.** That's about 320 labels with N=200 prompts, at $0.825 / $4.125 per million tokens, reasoning included.
- **gpt-6-luna, under $1:** agent naming and the frozen summaries.

### Budget and spend guard

**Plan for the whole experiment**, against the $50 cap:

| Item | Estimate |
| --- | --- |
| Phase 1 fixtures | $8 |
| Smoke runs (×3) | $0.50 |
| Phase 1 baseline (`full`) | $8 |
| Phase 2 fixtures + baseline | $4 |
| Reduced phase 3 fixtures + baseline | $2 |
| Iterating on solutions (about 10 × `dev-quick`, plus tuning archiving's D and the history cap's k on dev) | $5 |
| Final test runs: version 1 (records, ID routing, retrieval) and version 2 (+ archiving, history cap), each phase 1 $6 + phase 2 $2.50 + phase 3 $1 | $19 |
| **Total** | **about $46.50, leaving about $3.50 spare** |

**Spend guard:**

- **Ledger.** Every model call's cost comes from `usage.cost`. Every run and every fixture step appends its actual total to `results/spend_ledger.jsonl` as `{"run_id", "kind", "cost_usd", "date"}`. Generation scripts write to the ledger too.
- **Per-run cap.** A run stops cleanly when its spend reaches `budget.max_cost_usd`, or a `--max-cost` flag. In-flight calls finish, results so far are written, and the report says the run was capped. A capped run can't be used for comparisons.
- **Pre-run check.** Before starting, `run.py` estimates the run's cost as planned turns × measured cost per turn × `estimate_margin`. The measured cost per turn comes from the latest smoke run for the same method and model, or from the estimates above until one exists. If the ledger total plus the estimate would exceed `total_cap_usd`, the run refuses to start.
- **A second guard outside the harness:** a dedicated OpenRouter API key for the experiment, with its credit limit set to $50.

**What to cut if measured costs come in high.** These are pre-agreed, in this order, so nobody has to decide under pressure:

1. The second solution version gets only a phase 1 test run.
2. The final phase 3 run uses 8 tasks instead of 15.
3. Iterations use `smoke` instead of `dev-quick`.
4. Only one solution version gets final test runs.

Repetitions, roster sizes and case counts are never cut after the baseline, because comparisons need identical settings.

## Phase 2: parallel-split cases (outline)

Tests the hypothesis that single-delegation routing looks reasonably good while parallel-split cases do worse.

- **Case format:** like single-turn, but `label` becomes `expected`, a list of 2 to 4 work items. Each item is `{"item_id", "description", "label": REUSE | REUSE_ANY | CREATE}`. An optional `allowed_merges` lists item groups that may share one delegation. Drafted from the same thread catalog, with the same labeling and review process. About 40 test and 20 dev templates.
- **Sizes and reps:** 2 reps, at N = 10, 50, 100, 125, 200 on test and N = 10, 200 on dev, the same as the sequences.

**Why matching needs a judge.** When one message asks for several things, the model may make several delegations. Before each one can be scored, the scorer has to know which piece of the request it was meant for.

Example: *"forward the AWS invoice to my accountant and find me flights to Denver for next Friday"*. Item 1 is REUSE of the AWS invoice thread, and item 2 is CREATE. Suppose the model calls:

- `send_message_to_agent("AWS Invoice Lookup", ...)`
- `send_message_to_agent("Denver Flight Search", ...)`

The first call went to an existing agent whose thread is the AWS invoice, so it matches item 1 by thread with no judgment needed. The second created a new agent, which has no thread yet. Code can't reliably tell from free text whether its instructions describe the flights item, a second attempt at the invoice, or something else. A judge model makes that call.

**Matching delegations to items (open question 5):**

1. **Delegations to existing agents** are matched to items by thread: the item whose label includes that agent's thread. No judge.
2. **Delegations that create an agent** go to the judge: `google/gemini-3.8-flash`, pinned, with the prompt hashed. It reads the delegation's `instructions` and the descriptions of the items not yet matched, and returns the item ids the delegation covers, or none. Before first use, check it against 30 delegations that the implementing agent labels by hand, and require at least 90% agreement. Judge calls count toward the run's cost.
3. Build a bipartite graph between delegations and the items they cover. Weight 2 where the routing target also fits the item's label, 1 for a covering match only. Pick the maximum-weight one-to-one matching by brute force, which is enough for up to 4 items.
4. Classify each matched pair with phase 1's primary-delegation classifier.
5. An unmatched item is `missed_delegation`, tagged `merged` when its covering delegation was matched to another item and the merge isn't allowed. An unmatched delegation is `extra_delegation`.

- **Cost:** about $2.50 per test run (routing about $0.70, judge about $2). Fixtures plus the baseline cost about $4.
- **Metrics:** per-item accuracy (phase 1's definitions applied per item), case-level all-correct rate, split recall (items that got their own delegation), and the hypothesis check: per-item accuracy against phase 1 accuracy on the same threads and N.
- **Reused from phase 1:** fixtures and the world model, the roster builder, the method interface (no change, since `RoutingOutput` already lists all delegations), the runner's `single` suite, the outcome classifier and tags, metrics and report machinery, configs, the ledger and `compare.py`. New: the case schema, `matching.py` and a report section.
- **Feeds phase 3:** these cases are what form real multi-agent batches.

## Phase 3: execution harness (outline)

For execution task success against history length, execution agent prompt size, and batch latency.

**Isolation.** Every side effect is redirected, without changing `server/`:

- **Gmail:** patch `execute_gmail_tool` and `get_active_gmail_user_id` wherever they're imported by name (`execution_agent/tools/gmail.py`, `tasks/search_email/gmail_internal.py`, `tasks/search_email/tool.py`). The replacement is a `FixtureGmail` over a JSON inbox (messages with ids, thread ids, from, to, subject, body, date, labels), generated from the same thread catalog, so routing and execution share one world. It implements the Composio actions these tools call (`GMAIL_FETCH_EMAILS` with a subset of the query syntax: `from:`, `to:`, `subject:`, `newer_than:`, `label:`, free text; plus create, send and delete draft, reply, forward, list drafts, contacts, people). Response shapes are copied from what `email_cleaner.py` and the search task parse. Every write is recorded as a side effect.
- **Execution logs:** an `ExecutionAgentLogStore` at a temp dir, patched into every `get_execution_agent_logs` reference.
- **Triggers:** the trigger store pointed at a temp SQLite file. The scheduler is not started.

**Execution task success against history length (open question 6):**

- **Reduced version (the planned one, to fit the budget):** 15 test and 8 dev gradeable tasks, with histories at L in {0, 50} past tasks, 3 reps, so 90 runs on test. The full version (30 tasks, L in {0, 5, 20, 50}) is an extension if budget remains.
- **Tasks:** reply to the right thread, draft to the right person, find a figure, create a trigger with the right schedule. Some contain stale-fact traps: the history says one amount, the inbox now says another. Of the 15 test tasks, 4 (and 2 of the 8 dev tasks) are **old-detail tasks**: they need something only an older task in the history holds, such as an email id or a detail agreed 30 tasks ago. These make the cost of a history cap visible.
- **Histories:** synthetic agent logs in `log_store` format, built in code like the long conversation histories, from the same agent's thread and nearby threads.
- **Runs:** each run takes about 3 to 6 calls, including the search sub-agent.
- **Grading, step 1 (deterministic):** checks on recorded side effects (right action, thread or message id, recipient, trigger fields, nothing sent without confirmation).
- **Grading, step 2 (judge):** `google/gemini-3.8-flash` checks the response text against a per-task rubric (required facts present, no stale facts). Checked against 20 hand-graded runs before use.
- **Success:** a run succeeds only if every deterministic check passes and the judge passes.
- **Execution agent prompt size:** `prompt_tokens` per execution call against L. Median and p95.

**History cap (a candidate for solution version 2):**

- **Configuration.** The execution side gets the same swap point as routing: an `ExecutionConfig` in the run config with `conversation_limit` (`null` for the baseline). The phase 3 harness builds execution agents through a subclass of `ExecutionAgentRuntime` that passes `ExecutionAgent(agent_name, conversation_limit=...)`. Once version 2 changes `server/` to read the limit from settings, the harness uses that code path instead and records the setting.
- **What the limit counts.** It counts `<agent_request>` entries. The current request is already in the log when the agent runs, so a limit of k keeps the current task plus k − 1 past ones.
- **Tuning k (dev only):** 8 dev tasks at L = 50 with k in {5, 10, 20}, 1 rep. That's 24 runs, about $0.30. Pick the smallest k whose success rate is within 5 points of no cap, and record it.
- **Test:** version 2's phase 3 run repeats only L = 50, since a cap doesn't change L = 0. That's 45 runs. Report success with and without the cap, old-detail tasks separately, and execution prompt size.

**Batch latency:**

- **(a) Deterministic mode.** Replace `ExecutionAgentRuntime.execute` with a stub that sleeps for scripted durations, with K in {1, 2, 4, 8} agents per batch. Patch `_dispatch_to_interaction_agent` to record the time instead of calling the interaction agent. This measures head-of-line wait (dispatch time minus each agent's finish time) and the 90-second timeout behavior with no model calls, in seconds.
- **(b) Live mode.** Phase 2 parallel cases with real execution agents on `FixtureGmail`. It gives the same timings plus each agent's own duration.

**Cost:** about $1 per reduced test run, and about $2 for fixtures plus the baseline (estimates). Deterministic batch timing is free. Live batch timing reuses phase 2's test cases at N=10 and N=200 only.

**Reused:** `llm.py` (pinning, usage, retries), config, manifest, ledger, results and report machinery, the thread catalog, and phase 2's cases and delegations as inputs.

## Answers to the open questions

From [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md#open-questions-for-the-experiment-design):

1. **Synthetic roster names:** the real interaction prompt names an agent for each thread's opening request, with an empty roster and history and the pinned model. Collisions are resampled, and the names are frozen. See [Generating agent names](#generating-agent-names-open-question-1).
2. **Cases and repetitions:**
   - Single-turn: 120 test and 60 dev templates with fixed quotas per label and style, 2 reps at all six roster sizes.
   - Sequences: 8 test and 4 dev, 12 turns each, 2 reps per mode, at N = 10, 50, 100, 125, 200 on test and N = 10, 200 on dev.
   - The size was chosen for the deadline and the $50 budget (agreed 2026-10-25). The precision this buys is in [Uncertainty](#uncertainty).
3. **Model settings:**
   - The model is `openai/gpt-6-luna` (agreed 2026-10-25).
   - The alias is checked against the canonical slug `openai/gpt-6-luna-20260922`.
   - The provider is pinned to OpenAI with no fallbacks (agreed).
   - No temperature, because the model doesn't accept it.
   - A fixed seed per call position, for best-effort replay.
   - No reasoning parameters, as in production.
4. **Summarization:** kept as in production (agreed). Sequences start at 96 entries, so the real summarizer runs during each sequence. 30% of single-turn cases carry a frozen output of the real summarizer plus its tail. The report breaks results down by history type and by `target_name_visible`, which shows whether summarization dropping agent names hurts routing.
5. **Parallel-split matching:** an LLM judge for which items a delegation covers, then a maximum-weight matching, then phase 1's classifier per matched pair. See [Phase 2](#phase-2-parallel-split-cases-outline).
6. **Execution task success grading:** deterministic checks on mocked side effects first, then a rubric judge for the response text, with the judge validated on a hand-graded sample. See [Phase 3](#phase-3-execution-harness-outline).

## Known limitations

- Execution agents don't run in phases 1 and 2. Result lines are canned, and the interaction agent's turn on each result is replaced by a canned reply.
- Summarization runs synchronously between turns. In production it races with the next message.
- Single-turn rosters are clean (one agent per thread). Real rosters already contain duplicates, which the carried-forward sequences produce, but only from the sequence's own turns.
- Cases are synthetic and LLM-drafted. Topics and styles may not match real use.
- Agent ages are synthetic. Real dormancy patterns, such as agents kept busy by recurring triggers, aren't modeled. Archiving rules that depend on trigger activity can't be tested in phase 1.
- Long histories are assembled from templates, so they read more uniformly than real conversations. They also mention only the case's own agents. In production, a user with 200 agents would have a history naming many more of them. This keeps roster size the only variable between sizes, but it may make large-N routing look easier than it is.
- Latency depends on concurrency and on OpenRouter load, so latency comparisons are only meaningful between runs with the same concurrency, ideally on the same day.
