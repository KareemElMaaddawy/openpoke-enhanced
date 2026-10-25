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

### From the write-up

- Archiving dormant agents
- Clustering related agents
- A hot cache of recently active agents

## Experiments

None yet. Record each one here: setup, metric, result, conclusion.

## Decisions

- **2026-10-25: Metrics agreed.** The primary, secondary and guardrail metrics in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md#metrics) are what solutions will be judged against. Targets are set after a baseline is measured.
