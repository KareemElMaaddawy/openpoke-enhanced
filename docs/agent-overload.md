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

Each of these needs evidence before it shapes a design:

1. **Routing accuracy drops as the roster grows.** The right agent gets missed, or a duplicate is spawned.
2. **Duplicates multiply.** Exact-name matching combined with names chosen freely by the LLM could make the roster grow faster than the number of real work threads.
3. **Token cost and latency grow linearly with roster size** on every interaction agent turn, including turns that don't route anything.
4. **Names alone carry too little information** to route well, even when the roster is small.

## Success criteria (to be agreed)

Open. Candidates to discuss:

- Routing accuracy (did it pick the correct existing agent, or correctly create a new one) at roster sizes such as 10, 50, 200, 500.
- Duplicate-agent rate over a scripted multi-day session.
- Roster-related tokens per interaction agent turn.
- Added latency from any retrieval step.

## Candidate directions (from the write-up, not yet evaluated)

- Semantic search over agent descriptions (requires agents to *have* descriptions first)
- Archiving dormant agents
- Clustering related agents
- A hot cache of recently active agents

Each one needs: the hypothesis it addresses, its cost, its failure modes, and an experiment.

## Experiments

None yet. Record each one here: setup, metric, result, conclusion.

## Decisions

None yet.
