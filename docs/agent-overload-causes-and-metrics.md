# Agent overload: causes and metrics

What causes execution agent overload in this codebase, sorted into design causes and implementation causes, and the metrics a solution will be judged against. The problem statement and the running log of experiments and decisions stay in [agent-overload.md](agent-overload.md).

Every cause below has been checked in the code. Its **effect** on routing, cost or latency has not been measured yet. Measuring it is what the metrics are for.

## Two kinds of overload

1. **Single-agent overload.** One agent has too many tools, instructions or tokens in its context. It picks the wrong tool, drifts from its goal, and gets slower and more expensive.
2. **Multi-agent overload.** The cost of coordinating agents (routing, handoffs, passing messages, waiting on each other) outgrows what splitting the work buys.

They are linked. When an orchestrator routes among N agents, choosing one is a selection problem, so adding agents (type 2) tends to show up as type 1 inside the orchestrator. In OpenPoke the cause is mostly type 2 (agents are created freely and never removed). The symptom is mostly type 1, felt by the interaction agent.

## How causes are classified

- **Design**: built into how agents, routing and memory are structured. Fixing it means changing the architecture.
- **Implementation**: a detail of the current code. It can be fixed while keeping the architecture as it is.

## Design causes

### D1. One generative agent does all the routing, plus everything else

The interaction agent decides whether to delegate, picks an existing agent or creates a new one, writes the instructions, and talks to the user, all in one prompt that shows every agent. Routing is tied to the other jobs and always sees the full set of choices.

- Overload type: 1 (selection among many options in context)
- Note: embedding-based or discriminative routing could take over "which existing agent matches?", but agents are created at runtime, so a fixed-class classifier doesn't fit; it would have to be similarity-based. The "nothing matches, create one" decision then becomes a threshold choice, which is where duplicates come from. A likely shape is retrieval that narrows to a few candidates, then the LLM chooses. This is a direction to test, not a decision.

### D2. Nothing has a global view of the work

Each execution agent sees only its own log. The interaction agent sees agent names and its own summarized conversation, never the execution logs. When two agents handle the same thing, neither knows about the other, and both can act on it (reply to the same email, set the same trigger, since each agent owns its triggers).

- Overload type: 2 (no coordination between agents)
- Note: isolation is also what keeps each agent's context small. The gap is the lack of task identity and deduplication, not isolation as such. Shared memory would fix it but brings context bloat back.

### D3. Execution agents are not specialists

Every execution agent gets the same tools: Gmail, the `search_email` task and triggers (`server/agents/execution_agent/tools/registry.py`). Agents differ only in name and history. Splitting into many agents therefore buys context isolation, not specialization: an "agent" is in practice a memory thread.

- Overload type: frames both
- Note: this suggests the problem is closer to indexing and retrieving memory threads than to multi-agent coordination. That changes which solutions apply.

### D4. No defined unit of identity or lifecycle

Nothing defines what one agent stands for (a task, a person, an email thread, a recurring job). The interaction agent decides each time. Agents are created per task but never retired: `roster.clear()` runs only on a full chat reset (`server/routes/chat.py`). The roster has no natural limit on its size.

- Overload type: 2 (number of agents grows without bound)

### D5. Every event funnels through the interaction agent

User messages, execution results (`batch_manager.py`) and important-email notifications (`importance_watcher.py` → `handle_agent_message`) all become interaction agent turns. Each turn pays the roster cost (I1), and more agents and tasks mean more inbound turns.

- Overload type: 2 (coordination cost grows with activity)

## Implementation causes

### I1. The full roster is rendered on every interaction agent turn

`prepare_message_with_history()` in `server/agents/interaction_agent/agent.py` renders every roster entry as `<agent name="..." />` for both user messages and agent messages (`runtime.py`, `execute` and `handle_agent_message`). Turns that route nothing pay the cost too.

- Overload type: 1
- Note: each entry is short (estimated 10 to 15 tokens, not measured), so 500 agents is a few thousand tokens. Routing quality is likely a bigger effect than token cost. Both need measuring.

### I2. The roster holds names only

`server/services/execution/roster.py` stores no description, last-active time or status. The name is the only routing signal. It also sets the execution agent's own purpose: `build_system_prompt()` uses `"Handle tasks related to: {name}"` (`server/agents/execution_agent/agent.py`).

- Overload type: 1 (too little information per option)

### I3. Exact-name matching silently creates agents

`send_message_to_agent` in `server/agents/interaction_agent/tools.py` reuses an agent only when the name string matches exactly. A near-miss name doesn't error, it creates a new agent, and that grows the roster and feeds I1.

- Overload type: 2 (feedback loop that grows the roster)

### I4. Different names can share one log file

The roster dedupes on the exact string. The log file name is a slug: lowercased, with punctuation turned into hyphens (`_slugify` in `server/services/execution/log_store.py`). "Email Keith" and "email-keith" become two roster entries that read and write the same log, so a "new" agent inherits another agent's history.

- Overload type: 2 (bug that adds roster entries and mixes histories)

### I5. Execution agents load their full history every run

`build_system_prompt_with_history()` puts the output of `load_transcript()` (the entire log) into the system prompt. `conversation_limit` exists but is never set, so every run includes everything. Tool arguments are capped at 200 characters and tool results at 500, so each task adds a bounded amount, but the total grows with every task. Agents woken by recurring triggers are probably the first to grow large (a guess, not measured).

- Overload type: 1 (inside the execution agent)

### I6. One batch waits for every delegated agent

The interaction agent's `ExecutionBatchManager` keeps one batch open and sends results back only when every pending agent in it has finished, with a 90-second timeout (`batch_manager.py`). The slowest agent holds up everyone's results, so the wait grows with the number of agents running at once. Trigger runs create their own `ExecutionBatchManager` (`trigger_scheduler.py`), so they don't share this batch.

- Overload type: 2

## Cross-cutting tension: reuse against spawn

Reusing agents keeps the roster small (fewer D4, I1 and I3 effects) but makes each reused agent's history longer (more I5). Spawning keeps histories short but grows the roster. A fix aimed at one side can make the other worse, so both sides have to be measured together.

## Metrics

Agreed on 2026-10-25. Targets are open until there is a baseline. Each metric should be reported at several roster sizes (for example 10, 50, 200, 500) so the result shows how it scales, not only a single number.

### Primary

| Metric | What it measures | Causes | How to measure |
| --- | --- | --- | --- |
| Routing accuracy | Share of delegations where the interaction agent reused the correct agent or correctly created a new one. Report the confusion breakdown: **false spawn** (created when it should have reused), **misroute** (reused the wrong agent), **false reuse** (reused when it should have created). | D1, I1, I2, I3 | Synthetic roster at N agents plus a fixed, labelled set of routing queries |
| Duplicate rate | Share of roster entries that duplicate an existing work thread. Also the **inflation ratio**: roster size divided by the number of distinct real work threads. | D4, I3, I4 | Scripted multi-day session with labelled threads, then count |
| Roster tokens per interaction agent turn | Tokens spent on `<active_agents>`, and total input tokens per turn, against roster size | I1, D5 | Token counts from the prompt the code builds |
| Execution agent prompt size | Prompt tokens per execution run against the number of past tasks for that agent. Report median and p95 across agents. | I5 | Token counts over a scripted session |
| Batch latency | Time from delegation to the interaction agent receiving results. Also **head-of-line wait**: dispatch time minus the agent's own finish time. | I6 | Timestamps in `batch_manager.py` with K agents running at once |

### Secondary

| Metric | What it measures | Causes |
| --- | --- | --- |
| Execution task success against history length | Whether a long history hurts how well an execution agent does its task (for example, acting on stale information) | I5 |
| Interaction agent latency per turn | Time per interaction agent turn against roster size | I1, D1 |
| Interaction agent turns per user request | How many extra turns agent messages and email notifications cause per request | D5 |
| Conflicting side effects | Duplicate actions on the same object, for example two agents replying to one email or two identical triggers | D2 |
| Dormant agent fraction | Share of agents unused in the last N days | D4 |
| Retrieval recall@k | For directions that retrieve candidate agents: share of queries where the correct agent is among the k retrieved. A miss usually becomes a false spawn. | D1, I1 |

### Guardrails

Any solution must not make these worse, even if it improves the metrics above:

- End-to-end task success: the user's request gets done correctly.
- User-facing latency, including any new retrieval or classification step.
- Cost per user request across all model calls, not only the interaction agent's.

### Ground truth needed

Routing accuracy, duplicate rate and conflicting side effects need labels: which agent a query should go to, and which roster entries belong to the same thread. These labels have to be built before those metrics can be measured. The token and latency metrics can be read directly from the running code.
