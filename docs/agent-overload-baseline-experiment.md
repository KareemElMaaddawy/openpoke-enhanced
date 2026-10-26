# Agent overload: baseline experiment inputs

What has been agreed for measuring the current system's baseline, as input for designing the experiment. The experiment itself (harness, fixtures, query set) is designed in [agent-overload-experiment-design.md](agent-overload-experiment-design.md), which also answers the open questions below. Causes and metric definitions are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md); the problem statement and decision log are in [agent-overload.md](agent-overload.md).

## System under test

The baseline measures the code as it is today:

- Roster entries are **names only**, matching `server/services/execution/roster.py`. Richer agent records are a later comparison against this baseline.
- Interaction agent and execution agent models as set in `server/config.py`: `openai/gpt-6-luna` for every role since 2026-10-25. It replaced `anthropic/claude-haiku-5.5`, which was a placeholder after Sonnet 4.4 was retired. The reason was that an improvement shown on a stronger model is more convincing.
- Execution agent tools as they are: Gmail, the `search_email` task and triggers.

**No new integrations before the baseline.** Every execution agent gets the same tools, and routing only sees agent names and the conversation, never tools. Adding integrations wouldn't change what routing sees, but it would change the system being measured. Test topics (for example AWS invoices or Uber Eats receipts) are things found **through email**, so Gmail covers them. Adding integrations later is its own experiment: more tools per execution agent is single-agent overload inside the execution agent, and new integrations may lead to more agents being created.

## How routing works today

There is no separate routing step. Routing is a side effect of the interaction agent calling `send_message_to_agent(agent_name, instructions)` (`server/agents/interaction_agent/tools.py`): an exact name match reuses that agent, anything else creates one.

What the model sees when it routes:

1. **System prompt** (`server/agents/interaction_agent/system_prompt.md`): prefer an existing agent unless the tasks can run in parallel; reuse an agent with useful context even if its name is unrelated; split complex requests into as many parallel delegations as possible.
2. **Tool description**: `agent_name` is a "human-readable name describing its purpose".
3. **`<conversation_history>`**: user messages, agent messages, the assistant's replies, and waits. Summarized once it reaches 100 messages (`conversation_summary_threshold`), keeping a summary plus the last 10.
4. **`<active_agents>`**: every roster name, in creation order (not order of last use).
5. **The new message**: `<new_user_message>`, or `<new_agent_message>` for execution results and email watcher alerts.

Two details that shape the test design:

- **The model never sees which agent it delegated to on earlier turns.** The conversation log (`server/services/conversation/log.py`) stores user messages, agent messages, replies and waits, but not `send_message_to_agent` calls. The only link between past work and an agent is the result line `[SUCCESS] agent_name: response` (`_format_batch_payload` in `batch_manager.py`). Test histories must include these lines, or reuse labels are unfair.
- **There may be no single correct answer.** The prompt allows reusing any agent with useful context, and creating one for parallel work, so a label can't always name exactly one agent.

## Roster sizes

10, 25, 50, 100, 125 and 200 agents.

## Metrics for the baseline

| Metric | How it's measured |
| --- | --- |
| Routing accuracy, with the outcome breakdown below | Routing harness: build the prompt with `prepare_message_with_history()`, call the model, capture the tool calls, don't run execution agents. Repeat each case (for example 3 times) since outputs vary. |
| Roster tokens per interaction agent turn | Same prompt with an empty roster and with N agents; the difference in prompt tokens reported by OpenRouter. Claude's tokenizer isn't available locally. |
| Duplicate rate | Multi-turn sequences with state, errors carried forward (see below): extra agents per thread at the end of a sequence. |
| Execution task success against history length | A separate execution harness: mocked Gmail tools over a fixture inbox, synthetic agent histories padded to different lengths, tasks whose output can be graded. The most expensive metric. |
| Batch latency, including head-of-line wait | Needs execution agents to actually run (or run with fixture delays). Batches only form when several agents are delegated at once, so this belongs with parallel-split cases. |

Recency lock is tracked alongside routing accuracy (see below).

## Order of work

1. **Single-delegation cases**: each message should produce exactly one delegation (or none). Single-turn first, then multi-turn sequences.
2. **Parallel-split cases**: one message should produce several delegations. Scoring is harder because the delegations have to be matched to expected ones.
3. **Execution harness** for execution task success and batch latency.

**Hypothesis to confirm or reject:** single-delegation routing will look reasonably good, and parallel-split cases, which are closer to real use, will do worse.

## Test cases

A case is a **roster, a conversation history, a new message, and the expected routing**. The history matters because whether a follow-up should reuse an agent depends on it.

### Expected routing (one label per case, or per expected delegation in parallel-split cases)

| Label | Meaning |
| --- | --- |
| `REUSE(thread)` | Must go to the agent for one specific thread (for example, "reply to that email") |
| `REUSE_ANY(threads)` | Any of several threads' agents is acceptable |
| `CREATE` | New work that no existing agent covers |
| `NO_DELEGATION` | Should be answered directly (small share, since the prompt pushes delegation) |

Labels point at threads rather than agent names, so they still work in multi-turn runs where the model creates its own agents.

### Recorded outcome for each delegation the model makes

| Outcome | When |
| --- | --- |
| `correct_reuse`, `correct_create` | Matches the label |
| `misroute` | Reused an agent from the wrong thread |
| `false_spawn` | Created an agent when it should have reused one. Tagged `near_duplicate` when the new name closely resembles the expected agent's name |
| `false_reuse` | Reused an agent when it should have created one |
| `duplicate_reuse` | Reused an agent from the right thread, but a duplicate rather than the original (multi-turn only) |
| `missed_delegation`, `extra_delegation` | Number of delegations doesn't match the label |
| `invalid_call` | Malformed tool arguments |

### Metadata on each case, for breaking down results

- Roster size N
- Query style: explicit, paraphrased, implicit follow-up ("reply to that"), or near-distractor (Uber rides against Uber Eats)
- Message type: user message, execution result, or email watcher alert
- The target agent's position in the roster, to catch position bias
- How descriptive the target agent's name is
- In multi-turn sequences: the previous turn's agent and thread

## Multi-turn sequences with state

A sequence is a series of messages played in order, like a conversation over several days. After each turn, the harness updates the state with what the model actually did, and the next turn sees the updated state:

- **Roster**: any agent the model creates is added, so the next turn sees it, duplicates included.
- **Conversation history**: the user message is appended, plus a result line such as `[SUCCESS] aws_invoice_lookup: Found your October invoice...`. Execution agents are not run; each thread has a canned response so runs stay comparable.
- **Execution logs** (optional): only needed to catch two names sharing one log file (cause I4).

The harness keeps a map from agent to thread. Seeded agents are mapped up front; an agent the model creates is mapped to the thread of the turn that created it.

Each sequence is run two ways:

- **Errors carried forward**: the model's choices stick. Measures duplicate rate and how mistakes compound (a false spawn early on gives later turns two plausible agents to choose from).
- **Corrected each turn**: after scoring, the state is reset to what it should have been. Measures accuracy at each turn given a clean history, so a wrong pick can't be blamed on earlier mistakes.

## Recency lock

Recency lock is not known to happen in this codebase; it was reported in another project and needs to be found, not assumed. It shows up as a `misroute` where the chosen agent belongs to the previous turn's thread and the expected thread is different. Sequences need frequent topic switches for it to be measurable, and the corrected-each-turn runs give the cleanest signal.

## Open questions for the experiment design

- How to generate synthetic roster names that look like names the interaction agent itself would create (for example, by having it name agents for a set of seed tasks).
- How many cases per roster size and query style, and how many repetitions per case.
- Model settings for the harness (temperature, version pinning).
- Whether sequences should be long enough to trigger conversation summarization at 100 messages, which may drop agent names from the history.
- How to match the model's delegations to expected ones in parallel-split cases.
- Grading method for execution task success.
