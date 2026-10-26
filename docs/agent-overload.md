# Execution agent overload

The working document for the problem this repository exists to solve. Keep it up to date as hypotheses are tested and decisions are made.

## Problem statement

From the [OpenPoke write-up](https://www.shloked.com/openpoke), "Limitations": the whole roster of execution agents goes to the interaction agent on every request. Execution agents live indefinitely, so after days of use there can be hundreds of them, which the author describes as a relevance problem.

## Current behaviour (verified in code)

- `server/agents/interaction_agent/agent.py`: `prepare_message_with_history()` renders **every** roster entry as `<agent name="..." />` inside `<active_agents>` on every interaction agent turn, for both user messages and agent messages.
- The roster (`server/services/execution/roster.py`) holds **names only**: no description, no last-active time, no status. The only signal the interaction agent has for choosing an agent is the name it wrote itself.
- `server/agents/interaction_agent/tools.py`: `send_message_to_agent` matches on the **exact name string**. A near-duplicate name silently creates a new agent instead of reusing the existing one.
- Agents are never retired. `roster.clear()` runs only on a full chat reset (`server/routes/chat.py`).
- The system prompt tells the interaction agent to prefer reusing existing agents, so routing quality depends on how well it reads the roster.

## Why it matters (hypotheses, not yet measured)

The causes behind these, sorted into design and implementation causes, are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md).

Each of these needs evidence before it shapes a design:

1. **Routing accuracy drops as the roster grows.** The right agent gets missed, or a duplicate is spawned.
2. **Duplicates multiply.** Exact-name matching combined with names chosen freely by the LLM could make the roster grow faster than the number of real work threads.
3. **Token cost and latency grow linearly with roster size** on every interaction agent turn, including turns that don't route anything.
4. **Names alone carry too little information** to route well, even when the roster is small.

## Success criteria

Agreed. The metrics, and the causes each one targets, are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md#metrics). Targets stay open until there is a baseline.

## Candidate directions (not yet evaluated)

Each one needs: the hypothesis it addresses, its cost, its failure modes, and an experiment. Cause IDs (D1, I2, ...) refer to [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md).

### Richer agent records

Give each roster entry more than a name: a stable ID, a purpose or description, a last-active time, and a status (for example active, dormant, archived).

- Addresses: I2 (names carry too little information), I3 and I4 (routing by ID instead of by name string removes silent spawns from near-miss names and slug collisions), and lays the ground for D4 (lifecycle needs status and last-active time).
- Cost: new state in `roster.py` and a migration of `roster.json`. `send_message_to_agent` would take an ID for reuse, with a separate path for creating an agent. Someone has to write the purpose: most likely the interaction agent at creation time, which adds output tokens to that call.
- Failure modes: a purpose written at creation can be as vague as the name, and it goes stale as the agent's work drifts. Updating it means another LLM call per task. Longer entries also make the roster block bigger (I1), so on its own this may raise roster tokens per turn even if routing improves.
- Experiment: routing accuracy at fixed roster sizes with names only against names plus purpose, using the same labelled query set.

### Bounded retrieval of candidate agents

Instead of rendering the whole roster into `<active_agents>`, retrieve a bounded set of candidates (top-k) for each interaction agent turn, for example by embedding similarity over agent purposes, and let the interaction agent choose among them or create a new one. This replaces the write-up's "semantic search over agent descriptions".

- Addresses: I1 (roster tokens become roughly constant in roster size) and D1 (the generative model sees a few options instead of all of them).
- Depends on: richer agent records, since retrieval needs something better than names to match against.
- Cost: an embedding model and an index of agent records, kept in sync as agents are created or updated. An extra retrieval step adds latency to every turn.
- Failure modes: if the right agent isn't among the k candidates, the interaction agent can't pick it and will likely create a duplicate, so retrieval misses turn into false spawns. The retrieval query is a design question: the prompt is built before the interaction agent has worked out what to delegate, so the query has to come from the incoming message (and maybe recent history), which may not name the work clearly. Agent messages and email notifications need a query too. An alternative is giving the interaction agent a search tool, which lets it form its own query but costs an extra model turn.
- Experiment: recall@k of the correct agent at roster sizes 10 to 500 on the labelled query set, then routing accuracy and false spawn rate end to end against the full-roster baseline.

#### Retrieval only above a roster size N

Retrieval may not be needed while the roster is small. Below some size N, the scorer could see every record and skip retrieval, which keeps the pipeline simpler and removes retrieval misses as a failure mode. N comes from measurement, not a guess: it's the roster size where routing accuracy without retrieval starts to drop. The baseline sweep across roster sizes gives that number directly.

#### Scorer options

The pipeline is: richer records, then retrieval (only above N), then a scorer that returns reuse, create or ask. The scorer should be a swappable step so options can be compared on the same records and queries, and so there's a fallback if a hosted scorer is down. Every option has to make the "create a new agent" call, which is where duplicates come from.

| Scorer | How it works | Create-new decision | Main risk |
| --- | --- | --- | --- |
| Interaction agent over the top K | Current behaviour with a bounded list | Natural, the LLM decides | Routing stays tied to the interaction agent's other jobs (D1); possible recency lock |
| Separate small router LLM | One cheap structured-output call returning `{agent_id \| NEW \| ASK}` before the interaction agent runs | Natural, the LLM decides | An extra model call each turn |
| LLM judging one candidate at a time | Ask a small model "does this request continue agent X's work?" per candidate and read the probability of "yes" | Threshold on that probability | Needs the provider to expose token probabilities, which varies by model on OpenRouter (not checked) |
| TypeSafe Jev | Non-generative model returning typed answers with probabilities ([docs](https://docs.typesafe.ai/introduction), available through OpenRouter). Either one Choice question over the candidates plus `none_of_the_above`, or one yes/no (Noul) question per candidate in a single call | Explicit `none_of_the_above` probability (Choice), or a threshold (Noul) | Accuracy and speed figures are vendor-reported; an external dependency on every turn; requests over about 32,000 bytes of text run in a slower, less accurate long-context mode |
| Cross-encoder reranker | Scores each (request, record) pair, for example bge-reranker (self-hostable), Cohere Rerank or Voyage rerank | Threshold tuned on labelled data | Trained for document relevance, not "same ongoing work"; scores aren't calibrated |
| Embedding similarity alone | Uses the retrieval score directly: top match if it clears a threshold | Threshold | Weakest at telling similar agents apart (Uber rides against Uber Eats) |
| Fine-tuned classifier or reranker | A small model trained on labelled (request, record, correct or not) pairs | Learned | Overfitting to synthetic data; needs labels first |

Any scorer can also be combined with record signals such as last-active time, usage frequency and status. This is a main reason richer records are worth having. Weighting by recency is a deliberate bias toward recently used agents, though, which is the recency-lock failure, so its weight has to be tested, not guessed.

Jev is available through OpenRouter, so it can use the project's existing OpenRouter key and billing (checked 2026-10-25, [guide](https://openrouter.ai/docs/guides/community/jev)):

- Models `typesafe/jev-1.13` and `typesafe/jev-1.14` (pin a version for reproducibility), $0.042 per million input tokens, output free.
- Called through OpenRouter's Decisions API, `POST https://openrouter.ai/api/alpha/decisions`, with a state plus typed questions. The TypeSafe SDKs can also point at `https://openrouter.ai/api/v1/systemone`. The path is marked alpha, so the request format may change.
- Text requests over about 32,000 bytes run in TypeSafe's long-context mode, which TypeSafe says is slower and less accurate. That puts a practical cap on a single Choice question over every record, which is another reason for retrieval above N.
- `typesafe/jev-router` is a different product: it uses Jev to pick which LLM answers a chat request, and doesn't score caller-supplied options.

Proposed comparison: the interaction agent over the top K (control), a separate small router LLM, a cross-encoder reranker, and Jev as a single Choice question. Embedding similarity alone is the floor every option has to beat. Fine-tuning waits until a general-purpose scorer has shown the approach works.

### Archiving dormant agents

Give each agent a status. An agent unused for D days becomes `archived`. Archived agents are left out of what the interaction agent (or retrieval) sees, but they stay recoverable: they can be searched for and reactivated, and their logs are kept. This idea comes from the write-up.

- Addresses: D4 (the roster gets a real limit instead of growing without bound), I1 (fewer entries per turn even without retrieval). It also reduces how much retrieval has to do.
- Depends on: richer agent records, for status and last-active time.
- Cost: a status field and a last-active time updated on every delegation, an archiving rule (run on each turn or on a timer), and a way back to an archived agent. That could be a search over archived records when nothing active matches, or reactivation when the user names the agent's work.
- Failure modes: the user returns to an old thread and its agent is archived, so the system spawns a duplicate. That's a false spawn caused by archiving. The choice of D trades roster size against those misses. Recurring triggers keep an agent busy without the user mentioning it, so "unused" has to count trigger runs, or an agent whose trigger still runs must never be archived.
- Experiment: routing accuracy and false spawn rate on cases where the user returns to a thread whose agent was last active 15 to 60 days earlier, against the baseline. Also the dormant agent fraction and the roster size actually shown per turn. D is tuned on dev only.

### Capping execution agent history

Set `conversation_limit` on execution agents, so each run's system prompt includes only the last k tasks of the agent's log instead of all of it. The setting already exists in `ExecutionAgent` and is never set: `ExecutionAgentRuntime` builds `ExecutionAgent(agent_name)` without it.

- Addresses: I5 (execution prompt size stops growing with the number of past tasks). It also counters the reuse-against-spawn tension: better routing means more reuse and longer histories, and a cap keeps those histories bounded.
- Cost: one setting, plus choosing k. The existing cut counts `<agent_request>` entries. The current request is already in the log when the agent runs (`send_message_to_agent` records it first), so a limit of k keeps the current task plus k − 1 past ones.
- Failure modes: a task that needs something from an older task (an email id, an agreed detail) loses it, and the agent fails or asks again. A hard cut by task count may also split a task's entries in the wrong place if the log format changes. Summarizing older history instead of dropping it is an alternative, at the cost of an extra model call.
- Experiment: phase 3 execution task success and execution prompt size at 50 past tasks, with and without the cap, on the same tasks. Include tasks that need a detail from an older task, so the cost of the cap is visible. k is tuned on dev only.

### Planned solution versions

To fit the time and the $50 budget, candidates are bundled into two versions, each run once on the test split (details in [agent-overload-experiment-design.md](agent-overload-experiment-design.md#budget-and-spend-guard)):

1. **Version 1:** richer records and ID routing, plus bounded retrieval above N with a scorer.
2. **Version 2:** version 1 plus archiving dormant agents and capping execution history.

Which piece contributed what is checked with ablations on the dev split.

### From the write-up

- Clustering related agents
- A hot cache of recently active agents. This could also cover retrieval's weak spot: implicit follow-ups such as "reply to that" give retrieval nothing to search on.

## Experiments

None run yet. Record each one here: setup, metric, result, conclusion.

The agreed inputs for the baseline experiment (system under test, roster sizes, metrics, labels, multi-turn design) are in [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md).

## Decisions

- **2026-10-25: Metrics agreed.** The primary, secondary and guardrail metrics in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md#metrics) are what solutions will be judged against. Targets are set after a baseline is measured.
- **2026-10-25: Baseline experiment scope.** Roster sizes 10, 25, 50, 100, 125 and 200, names only as in today's code. Metrics measured first: routing accuracy, roster tokens per turn, duplicate rate, execution task success against history length, and batch latency (execution task success moved up to primary). Single-delegation cases first, then parallel-split cases. No new integrations before the baseline. Details in [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md).
