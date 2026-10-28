# OpenPoke Enhanced

A fork of [OpenPoke](https://github.com/shlokkhemani/openpoke) ([write-up](https://www.shloked.com/writing/openpoke)) that tackles **execution agent overload**. OpenPoke is an open-source take on the Poke assistant: an interaction agent that talks to the user and hands work to execution agents, with Gmail tools through Composio, reminders, an important-email watcher and a Next.js UI.

This README is the take-home submission. It explains the problem, the starting hypotheses, the solution, how it was tested, and what the tests showed.

## Summary

- **The problem.** OpenPoke never removes execution agents, and the interaction agent sees all of them, by name only, on every turn. On a labelled test set, routing accuracy fell from 84% with 10 agents to 74–77% with 50 or more, and the roster costs about 11 tokens per agent on every call.
- **The solution** (version 1, `make dev ROUTING=records`). Each agent gets a record (ID, purpose, recent work), the interaction agent routes by ID, and above 50 agents it sees only the 5 most relevant records instead of the whole roster.
- **The result** on the held-out test split, run once with targets set beforehand: accuracy rose from 77.7% to 88.8% (+11.1 points, 95% CI [+5.6, +16.9]) and is higher at every roster size. From 100 agents up, roster tokens per turn stay flat at about 2,200, which is 66% below the baseline at 200 agents.
- **The cost.** Version 1 traded one kind of error for another. It nearly eliminated the baseline's main errors (sending new work to an existing agent, or to the wrong one), but it now creates a new agent for work an existing agent owns on 15% of such turns, against 0.4% before. Those duplicates build up over a conversation. The right agent was almost always in the list when it happened, so my working assumption is that the problem is the create decision, which the interaction agent makes alone. A separate decision step, a scorer, that has to rule out the listed candidates first should help. That's untested; the slot for it exists, and the options are in [section 10](#10-with-more-time).
- **Tests and evaluators.** A routing evaluation harness ([`evals/agent_overload/`](evals/agent_overload/)) with a frozen, labelled case set, deterministic scoring and paired statistics, plus 310 unit tests that make no API calls.

## Contents

1. [The problem](#1-the-problem)
2. [Starting hypotheses](#2-starting-hypotheses)
3. [The solution: richer records and bounded retrieval](#3-the-solution-richer-records-and-bounded-retrieval)
4. [How it was tested](#4-how-it-was-tested)
5. [Results](#5-results)
6. [Problems found along the way](#6-problems-found-along-the-way)
7. [What changed in the code](#7-what-changed-in-the-code)
8. [Running it](#8-running-it)
9. [Hurdles](#9-hurdles)
10. [With more time](#10-with-more-time)

## 1. The problem

How routing works in OpenPoke:

- The **interaction agent** is the only agent the user talks to. It hands work to **execution agents** with `send_message_to_agent(agent_name, instructions)`. If the name exactly matches an existing agent, that agent gets the work along with its history. Any other name creates a new agent.
- The **roster** of execution agents is a list of names ([`roster.py`](server/services/execution/roster.py)). Agents are never removed, except by a full chat reset.
- The whole roster is rendered into the interaction agent's prompt as `<agent name="..." />` lines on every turn: for user messages, execution results and email alerts alike, whether or not the turn routes anything.

So the roster only grows, and the interaction agent's prompt grows with it. After weeks of use there can be hundreds of agents, each described only by a name the model chose when it created it. The interaction agent suffers most. On every turn it has to pick the right agent out of all of them, on top of its other jobs: talking to the user, writing instructions, and deciding whether to delegate at all.

Two kinds of overload are involved:

1. **Multi-agent overload.** Coordinating agents (routing, handoffs) costs more than splitting the work saves. In OpenPoke, agents are created freely and never retired, so their number has no limit.
2. **Single-agent overload.** One agent's context holds too many options or tokens, so it chooses badly and gets slower and more expensive. In OpenPoke this is the interaction agent choosing among every agent in its prompt. Execution agents also load their full history on every run, which is a second, smaller case.

The two are linked. The cause is mostly multi-agent (agents pile up), and the symptom is mostly single-agent, felt by the interaction agent. The full list of causes, each checked in the code, is in [docs/agent-overload-causes-and-metrics.md](docs/agent-overload-causes-and-metrics.md).

## 2. Starting hypotheses

Going in, I assumed four things would happen as the roster grows. Each was made measurable before any solution was built.

| # | Hypothesis | How it's measured |
| --- | --- | --- |
| 1 | Routing accuracy drops: the right agent is missed, or the wrong one gets the work | Share of turns routed exactly right, at roster sizes from 10 to 200 |
| 2 | Duplicates multiply: near-miss names silently create new agents for existing work | Duplicate agents per thread of work at the end of multi-turn conversations |
| 3 | Token cost grows linearly with roster size, on every turn | Tokens spent on the roster block per turn |
| 4 | Names alone carry too little information to route well | Accuracy with names only against accuracy with richer agent records |

How each one turned out is in [Hypotheses revisited](#hypotheses-revisited).

## 3. The solution: richer records and bounded retrieval

Two ideas, used together:

- **Richer agent records** target hypotheses 4 and 2. They give the interaction agent more than a name to match on, and make reuse an explicit choice instead of a string match.
- **Bounded retrieval** targets hypotheses 1 and 3. The idea comes from retrieval-augmented generation (RAG): instead of putting every document in the prompt, retrieve the few most relevant ones and let the model work from those. Here the documents are agent records, and the model either picks one of them or creates a new agent.

Neither works well alone. A record costs about 147 tokens against about 11 for a name, so records without retrieval make the roster block 13 times larger. Retrieval over bare names has too little text to match on.

What happens on each interaction agent turn in `records` mode:

```
incoming message (user, execution result or email alert)
  │
  ├─ 50 or fewer active agents? ── yes ─▶ show every record
  │                             └─ no ──▶ retrieve the top 5: pinned agents first,
  │                                       then embeddings + BM25, fused by
  │                                       reciprocal rank fusion
  │
  ├─ scorer slot ─▶ version 1: pass-through, so the interaction agent decides
  │
  └─ interaction agent
     ├─ send_message_to_agent(agent_id, instructions) ─▶ existing agent
     └─ create_agent(name, purpose, instructions) ─────▶ new agent and record
```

- **Records.** Each agent has a stable ID, a name, a one-sentence purpose, its last 3 tasks with result snippets, a last-active time, a task count and a status. The interaction agent writes the purpose when it creates the agent. Recent work is updated in code on every dispatch and result, with no extra model call. Records are stored in `server/data/execution_agents/agents.json` next to the old roster, and an existing roster is imported on first start.
- **Routing by ID.** `send_message_to_agent` takes an `agent_id`. An unknown ID returns an error instead of creating an agent, so near-miss names can no longer spawn agents silently. New agents come only from a separate `create_agent(name, purpose, instructions)` tool, which refuses a name that would share a log file with an existing agent.
- **Bounded retrieval.** With up to 50 active agents, every record is shown. Above that, the prompt shows 5 and says the list is partial (`<active_agents shown="5" total="200">`). **Pinned** agents come first: those named in the latest execution results. Pins are what make "reply to that" work, since the message itself gives retrieval nothing to search on. The remaining slots are ranked by embedding similarity (`text-embedding-3-small`) and BM25 keyword match, combined with reciprocal rank fusion. If the embedding call fails, retrieval falls back to BM25 alone.
- **Scorer slot.** A step between retrieval and the prompt that can later decide to reuse, create or ask on its own. Version 1 ships only a pass-through, so the interaction agent still makes the call.
- **Startup switch.** `legacy`, the default, is the original system. Tests check that its prompt and tools are byte-identical to the original code. `records` is version 1.

The thresholds (50 and 5) and the other parameters were chosen on the dev split ([section 5](#tuning-version-1-on-dev)). The full design is in [docs/agent-overload-records-retrieval-spec.md](docs/agent-overload-records-retrieval-spec.md).

## 4. How it was tested

The evaluation measures routing. Given a roster, a conversation and a new message, does the interaction agent send the work to the right agent, create a new one when it should, or answer directly? This is **phase 1** of the experiment design. Phase 2 (messages that should split into several delegations) and phase 3 (execution agents running against a fake inbox) were designed but not built; see [section 10](#10-with-more-time).

What went into phase 1, one piece at a time:

1. **A harness around the real code.** [`evals/agent_overload/`](evals/agent_overload/) runs the production interaction loop with the production prompt builder. Only the tools are stubbed, so nothing is sent and no execution agent runs. The routing method is a plug-in: `names_only` reproduces the original code, and `records_retrieval` is version 1. Cases, scoring and the report are the same for both.
2. **A synthetic world.** Work is modelled as *threads*, such as an AWS invoice, an email thread with a named colleague, or a gym reminder. Dev and test have separate threads and share nothing. Every agent name was written by the real interaction prompt for the thread's first request, so the names look like the ones the system really produces. Near-distractor pairs (Uber rides and Uber Eats) are included on purpose. Filler agents pad each roster to 10, 25, 50, 100, 125 or 200 agents.
3. **Labelled single-turn cases.** 120 test and 60 dev. Each case is a roster, a conversation history, a new message and the expected routing: reuse a given thread's agent, reuse any of several, create a new agent, or don't delegate. Messages come in four styles: explicit, paraphrased, implicit follow-up ("reply to that") and near-distractor. 30% of cases have long histories compressed by the real summarizer, and some messages are execution results or email alerts, as in production.
4. **Multi-turn sequences.** 8 test and 4 dev conversations of 12 turns, each played two ways. With *errors carried forward*, the model's choices stick, so an agent it created by mistake stays in the roster; this is where duplicates show up. With *corrected each turn*, the state is reset to the correct one after every turn, so mistakes can't compound.
5. **Labels.** Code planned each case and fixed its label before any text was written, so the quotas are exact ([`planning.py`](evals/agent_overload/generation/planning.py)). Claude Sonnet 5.5 then wrote each case to fit its planned label. Gemini 3.8 Flash, from a different model family, labelled every finished case blind, without seeing the planned label. Where the two disagreed, the case was fixed, rewritten or marked unsure against written labelling rules, and I reviewed the unsure ones plus a random sample of agreed ones. Of the 180 single-turn cases, 169 record agreement between the two labels. The case set was then frozen and hashed, and the harness refuses to run if anything in it changes.
6. **The evaluator.** Labels point at threads, and the harness knows which thread each agent belongs to, so scoring is deterministic and needs no LLM judge. Each turn is classified as correct, **false spawn** (created an agent when one should be reused), **misroute** (reused the wrong agent), **false reuse** (reused an agent for work that needed a new one), or a missed or extra delegation.
7. **Metrics.** Routing accuracy with that error breakdown, the share of duplicate agents at the end of carried-forward sequences, and roster tokens per turn. Roster tokens are measured by sending the same prompt with an empty roster and taking the difference.
8. **Statistics and discipline.** Each case runs twice. Differences between methods come with paired 95% bootstrap confidence intervals and a McNemar test ([`compare.py`](evals/agent_overload/compare.py)). All tuning used the dev split. The test split runs once per method version, and the pass/fail targets were written down before that run. Every run is committed under [`evals/agent_overload/results/`](evals/agent_overload/results/) with its full config.
9. **A budget guard.** A $50 cap for the whole experiment, enforced by a spend ledger, mandatory dry runs and per-run caps. The ledger shows about $17 spent, fixture generation included.

The system under test uses `openai/gpt-6-luna` for every model role. The design is in [docs/agent-overload-experiment-design.md](docs/agent-overload-experiment-design.md), and every command is in [docs/agent-overload-experiment-runbook.md](docs/agent-overload-experiment-runbook.md).

## 5. Results

### Baseline: names only

Run `20261027-035635-names_only-e5cf9a5a`, test split, single-turn cases. Misroute is a share of the turns that should reuse an agent; false reuse is a share of the turns that should create one.

| Agents in roster | 10 | 25 | 50 | 100 | 125 | 200 |
| --- | --- | --- | --- | --- | --- | --- |
| Accuracy | 84.2% | 82.5% | 76.7% | 73.8% | 73.8% | 75.4% |
| Misroute | 1.2% | 0.0% | 12.2% | 15.2% | 12.2% | 9.8% |
| False reuse | 55.8% | 59.6% | 48.1% | 48.1% | 53.8% | 63.5% |
| Roster tokens per turn | 309 | 792 | 1,587 | 3,216 | 4,017 | 6,363 |

- From 50 agents up, accuracy is 8 to 10 points lower than with 10.
- The main error is **false reuse**, not duplicates. When a request needs a new agent, names-only routing sends it to an existing one about half the time. Misroutes appear from 50 agents.
- False spawns are near zero at every size, and at most 1% of agents are duplicates at the end of carried-forward sequences.
- Roster tokens grow linearly, at about 10.65 tokens per agent per call plus a fixed 154.

### Tuning version 1 on dev

Dev runs answered four questions before the test run:

- **Do records help when every record is shown?** Yes. With 200 agents, accuracy rose 19.2 points [+10.0, +29.2], and it no longer fell as the roster grew. Most of the gain came from cases that need a new agent (29% correct before, 85% after).
- **Does retrieval keep that accuracy while capping tokens?** Mostly. With 5 retrieved records, accuracy was 3.3 points lower than with every record shown, a difference within noise. Roster tokens stayed flat at about 2,200 per turn, against 88,100 with every record shown at 200 agents. But false spawns rose to about 10%, and in most of them the right agent was in the list.
- **Do pins matter?** Yes. For implicit follow-ups ("reply to that"), the right agent was among the top 5 every time with pins, and 22% of the time without.
- **Does the written purpose add anything?** Not measurably. Accuracy without purposes was unchanged (0.0 points [−4.2, +4.2]). Purposes were kept, because this was tested only with retrieval, and the product writes them anyway.

Showing 8 records instead of 5 barely changed false spawns (9.4% against 10.4%), so the length of the list isn't the cause.

Chosen parameters: show every record up to 50 agents (the largest size below the baseline's dev accuracy drop), retrieve 5 above that (the smallest number that found the right agent at least 95% of the time with 200 agents), pins on (at most 3), BM25 on, no recency weighting.

### Version 1 on the test split

Run `20261027-223042-records_retrieval-756d8701`, with the frozen config [`v1_records_test.json`](evals/agent_overload/configs/v1_records_test.json), run once. Two targets were set beforehand:

- **T1:** single-turn accuracy pooled over all roster sizes is above the baseline's, with the confidence interval above 0.
- **T2:** fewer roster tokens than the baseline at 100, 125 and 200 agents, where retrieval runs.

| Agents in roster | 10 | 25 | 50 | 100 | 125 | 200 |
| --- | --- | --- | --- | --- | --- | --- |
| Accuracy, baseline | 84.2% | 82.5% | 76.7% | 73.8% | 73.8% | 75.4% |
| Accuracy, version 1 | 91.2% | 95.0% | 91.2% | 84.6% | 85.4% | 85.4% |
| Difference [95% CI] | +7.1 [+1.7, +12.9] | +12.5 [+6.2, +18.8] | +14.6 [+7.9, +22.1] | +10.8 [+2.5, +19.2] | +11.7 [+3.7, +20.0] | +10.0 [+1.7, +17.9] |
| Roster tokens per turn, baseline | 309 | 792 | 1,587 | 3,216 | 4,017 | 6,363 |
| Roster tokens per turn, version 1 | 4,320 | 10,797 | 21,657 | 2,184 | 2,211 | 2,193 |
| False spawn, version 1 | 4.3% | 1.8% | 3.7% | 14.6% | 10.4% | 12.8% |
| Duplicate agents, baseline → version 1 | 0.0% → 12.5% | n/a | 0.0% → 25.2% | 1.0% → 29.5% | 0.0% → 25.3% | 1.0% → 26.4% |

**Routing accuracy: T1 passes.** Pooled over all sizes, accuracy rose from 77.7% to 88.8%, +11.1 points [+5.6, +16.9] (McNemar p = 3.5e-8), and it's higher at every roster size. False reuse fell by 46 points and misroutes by 8. With 200 agents, version 1 is still 10 points above the baseline.

**Token cost: T2 passes.** From 100 agents up, the roster block stays at about 2,200 tokens per turn however large the roster grows: 32%, 45% and 66% below the baseline at 100, 125 and 200 agents. Up to 50 agents every record is shown, so input tokens are higher than the baseline there by design, by 4,100 to 18,900 per turn. Lowering the threshold (`OPENPOKE_FULL_ROSTER_MAX`) trades some of that for more reliance on retrieval.

**Duplicates are the cost.** They were reported, not targeted. On turns that should reuse an agent, version 1 creates a new one 15.4% of the time, against 0.4% for the baseline. At the end of carried-forward sequences, 12.5% to 29.5% of agents are duplicates, against at most 1%. It happens with every record shown too, and even for explicit requests. Retrieval missed the right agent in only 28 of the 337 false spawns, and in 111 of them the right agent was listed **first**. So the duplicates come from the decision to create, not from retrieval.

**Multi-turn sequences show no accuracy gain** (+2.7 [−5.0, +9.1] carried forward, −0.8 [−5.6, +3.2] corrected each turn). The drop in false reuses and misroutes is cancelled by false spawns, which compound as duplicates build up within a conversation.

### Where the accuracy change comes from

Accuracy is a net score over every kind of routing error. Counting each test turn by its outcome (from each run's `turns.jsonl.gz`) shows the trade.

**Single-turn cases** (1,440 turns per method: 120 cases × 6 roster sizes × 2 reps)

| Turn outcome | Baseline | Version 1 | Change |
| --- | --- | --- | --- |
| Correct | 1,119 (77.7%) | 1,279 (88.8%) | +160 |
| False reuse | 171 | 27 | −144 |
| Misroute | 83 | 3 | −80 |
| False spawn | 1 | 78 | +77 |
| Other (missed delegation, or the right agent plus an extra delegation) | 66 | 53 | −13 |

**Carried-forward sequences** (960 turns per method: 8 sequences × 12 turns × 5 roster sizes × 2 reps)

| Turn outcome | Baseline | Version 1 | Change |
| --- | --- | --- | --- |
| Correct | 721 (75.1%) | 747 (77.8%) | +26 |
| Misroute | 144 | 12 | −132 |
| False reuse | 71 | 3 | −68 |
| False spawn | 6 | 150 | +144 |
| Reused a duplicate instead of the original | 2 | 21 | +19 |
| Other (missed or extra delegation, or the right agent plus an extra delegation) | 16 | 27 | +11 |

In single turns, version 1 removed 224 errors where work went to the wrong existing agent and added 77 false spawns, for 160 more correct turns: the interaction agent's tendency moved from over-reusing to over-creating. In carried-forward sequences, each duplicate stays in the roster and makes later turns harder, so the roughly 200 errors removed are offset by roughly 170 added, and the gain is within noise.

### What this means

Version 1 removes the roster-size load on the interaction agent. Above 50 agents it sees 5 records however large the roster grows, and it routes more accurately at every size. The baseline's main error, sending new work to an existing agent, has largely been traded for a new one: creating an agent for work an existing agent owns. Both runs used the same model, so this shift comes from what version 1 changed around it: the prompt, the separate `create_agent` tool, or what each record shows. Which of these is responsible isn't established yet. Retrieval keeps those duplicates from growing the prompt, but each one splits a thread's history and adds a near-identical candidate, and the roster grows 1.2 to 1.5 times faster than the work requires.

My hypothesis for the next version is that a dedicated **scorer**, which must rule out the listed candidates before a new agent is created, would bring false spawns back down without losing the accuracy gain. It hasn't been tested. The options are in [section 10](#a-scorer-to-cut-false-spawns).

### Hypotheses revisited

| # | Hypothesis | Baseline | Version 1 |
| --- | --- | --- | --- |
| 1 | Accuracy drops as the roster grows | **Holds**: 8 to 10 points lower from 50 agents up | Higher at every size, and still 10 points above the baseline with 200 agents |
| 2 | Duplicates multiply | **Not seen**: at most 1% duplicates; the main error was false reuse instead | **Appeared**: 12.5% to 29.5% duplicates in carried-forward sequences |
| 3 | Token cost grows linearly | **Holds**: about 11 tokens per agent per call | Flat at about 2,200 per turn from 100 agents; higher up to 50 |
| 4 | Names carry too little information | (needs a comparison) | **Holds**: on dev, records beat names by 19 points with 200 agents. The purpose itself added nothing measurable beyond recent work |

Every number, run ID and decision is in [docs/agent-overload.md](docs/agent-overload.md#experiments).

## 6. Problems found along the way

**The interaction loop could spin on `wait` until it failed.** The first smoke run showed gpt-6-luna calling `wait` over and over after delegating: 52 of 68 turns hit the loop's 8-call limit, at 6.7 model calls per turn instead of about 2. In the app, those turns end with "Reached tool iteration limit". The fix in [`runtime.py`](server/agents/interaction_agent/runtime.py) ends a turn when a response contains only `wait` calls, since `wait` means there's nothing more to send. In the smoke run, 55 of the 56 turns with a wait-only response made no delegation after it. The baseline and every later run use the fixed loop.

**Near-miss names created agents silently, and different names could share one log.** Reuse depended on an exact string match, so "AWS invoice" and "AWS Invoice Lookup" became two agents. Log files are named by a slug of the agent name, so "Email Keith" and "email-keith" were two roster entries writing to the same log. Records mode fixes both: reuse is by ID, `create_agent` refuses names whose slug is taken, and imported names that share a log become aliases of one record.

**Connecting Gmail no longer worked.** Composio retired `connected_accounts.initiate()` for Composio-managed OAuth configs. The connect flow now uses `link()` ([docs/gmail-composio-connection.md](docs/gmail-composio-connection.md)).

Gaps found but not fixed are listed under [Other gaps](#other-gaps).

## 7. What changed in the code

### Server: version 1

New files:

| Path | What it does |
| --- | --- |
| [`server/services/agents/records.py`](server/services/agents/records.py) | Agent record store (`agents.json`), import of the legacy roster, slug-collision checks |
| [`server/services/agents/text.py`](server/services/agents/text.py) | The text retrieval matches on, and the `<agent>` entry shown in the prompt |
| [`server/services/agents/purpose.py`](server/services/agents/purpose.py) | Prompt for writing a purpose for agents that have none |
| [`server/services/routing/candidates.py`](server/services/routing/candidates.py) | Candidate selection: every record up to the threshold, the top K above it |
| [`server/services/routing/pins.py`](server/services/routing/pins.py), [`query.py`](server/services/routing/query.py), [`lexical.py`](server/services/routing/lexical.py), [`embeddings.py`](server/services/routing/embeddings.py) | The retrieval channels: pinned agents, query building, BM25 and the embedding index |
| [`server/services/routing/params.py`](server/services/routing/params.py) | Retrieval parameters, set to the values that were tested |
| [`server/services/routing/scorer.py`](server/services/routing/scorer.py) | The scorer interface and the version 1 pass-through |
| [`server/agents/interaction_agent/routing.py`](server/agents/interaction_agent/routing.py) | `LegacyRouting` and `RecordsRouting`, picked at startup |
| [`server/agents/interaction_agent/tools_records.py`](server/agents/interaction_agent/tools_records.py) | `send_message_to_agent(agent_id, ...)` and `create_agent(name, purpose, ...)` |
| [`server/agents/interaction_agent/records_prompt.py`](server/agents/interaction_agent/records_prompt.py), [`system_prompt_records.md`](server/agents/interaction_agent/system_prompt_records.md) | Records-mode message builder and system prompt; only the routing section differs from the original |
| [`server/tests/`](server/tests/) | 127 unit tests, including legacy parity |

Changed files:

| Path | Change |
| --- | --- |
| [`server/agents/interaction_agent/runtime.py`](server/agents/interaction_agent/runtime.py) | Calls the routing strategy at three points; ends a turn at a wait-only response |
| [`server/config.py`](server/config.py) | Routing mode, the full-roster threshold and embedding settings; every model role set to `openai/gpt-6-luna` |
| [`server/server.py`](server/server.py), [`server/app.py`](server/app.py) | The `--routing` flag; record import and a log line for the mode at startup |
| [`server/routes/chat.py`](server/routes/chat.py) | A chat reset also clears records and embeddings |
| [`server/routes/meta.py`](server/routes/meta.py), [`server/models/meta.py`](server/models/meta.py) | `routing_mode` in `GET /api/v1/meta` |
| [`Makefile`](Makefile), [`.env.example`](.env.example) | `ROUTING=` and `OPENPOKE_FULL_ROSTER_MAX` |

Left unchanged on purpose: the original system prompt, the legacy tools, the legacy prompt builder, execution agents, logs and triggers. Logs and triggers stay keyed by agent name, and the ID exists only in the routing layer.

### Evaluation harness

All new, under [`evals/agent_overload/`](evals/agent_overload/):

| Path | What it does |
| --- | --- |
| [`harness/`](evals/agent_overload/harness/) | Conversation state, roster building, scoring (the evaluator), metrics, the report, the model client and the spend guard |
| [`harness/methods/`](evals/agent_overload/harness/methods/) | The two routing methods: `names_only` (baseline) and `records_retrieval` (version 1) |
| [`generation/`](evals/agent_overload/generation/) | The scripts and prompts that built the case set |
| [`fixtures/v1/`](evals/agent_overload/fixtures/v1/) | The frozen, hashed case set, with its labelling and review records |
| [`configs/`](evals/agent_overload/configs/) | Run configs: the baseline, the dev variants and the frozen version 1 test config |
| [`run.py`](evals/agent_overload/run.py), [`compare.py`](evals/agent_overload/compare.py), [`retrieval_probe.py`](evals/agent_overload/retrieval_probe.py) | Command-line tools: run a config, compare two runs, measure retrieval alone |
| [`results/`](evals/agent_overload/results/) | Every run, probe and comparison, plus the spend and test ledgers |
| [`tests/`](evals/agent_overload/tests/) | 183 unit tests, including fake-model end-to-end runs |

### Docs

The working docs are in [`docs/`](docs/README.md): the [problem and decision log](docs/agent-overload.md), [causes and metrics](docs/agent-overload-causes-and-metrics.md), [baseline inputs](docs/agent-overload-baseline-experiment.md), [experiment design](docs/agent-overload-experiment-design.md), [runbook](docs/agent-overload-experiment-runbook.md), [records and retrieval spec](docs/agent-overload-records-retrieval-spec.md), [Makefile commands](docs/makefile.md) and [Gmail via Composio](docs/gmail-composio-connection.md).

## 8. Running it

Requires Python 3.10+, Node.js 18+ and npm 9+. The `make` targets need macOS or Linux.

### Setup

```bash
git clone https://github.com/KareemElMaaddawy/openpoke-enhanced
cd openpoke-enhanced
make setup
```

`make setup` creates `.env` from `.env.example`, creates `.venv` and installs the backend and frontend dependencies. Then fill in `.env`:

- `OPENROUTER_API_KEY`: every model call goes through [OpenRouter](https://openrouter.ai/).
- `COMPOSIO_API_KEY` and `COMPOSIO_GMAIL_AUTH_CONFIG_ID`: Gmail through [Composio](https://composio.dev/).

`make check-env` confirms the keys are set. Once the app is running, open <http://localhost:3000> and connect Gmail under *Settings → Gmail*.

### Choosing the routing mode

| Command | What runs |
| --- | --- |
| `make dev` | API server (with reload) and web app together, with the original names-only routing. Ctrl-C stops both |
| `make dev ROUTING=records` | Version 1: records, ID routing, and retrieval above 50 agents |
| `OPENPOKE_FULL_ROSTER_MAX=3 make dev ROUTING=records` | Version 1 with retrieval from 4 agents up, to see it without creating 50 agents |
| `make start ROUTING=records`, `make stop`, `make logs` | The API server in the background, logging to `.server.log` |
| `make web` | The web app only, against a server from `make start` |
| `make health` | Checks that the API server responds |

The server logs the mode at startup, for example `Routing mode: records (embeddings openai/text-embedding-3-small@512, K=5, full_roster_max=50)`, and in records mode one `Routing candidates: ...` line per turn. `GET /api/v1/meta` also reports `routing_mode`. `make start` does nothing while a server is already running, so run `make stop` before switching modes. Both modes share `server/data/`, so reset the chat before comparing them by hand. More detail is in [docs/makefile.md](docs/makefile.md).

Without `make` (for example on Windows): create a Python 3.10+ virtual environment, run `pip install -r server/requirements.txt` and `npm install --prefix web`, then start `python -m server.server --reload --routing records` and `npm run dev --prefix web` in two terminals.

### Tests and evaluations

The unit tests make no API calls:

```bash
.venv/bin/python -m unittest discover server/tests
.venv/bin/python -m unittest discover -s evals/agent_overload/tests -t .
```

A free end-to-end run of the version 1 config against a deterministic fake model. Results go to `evals/agent_overload/results/_fake/`, which git ignores:

```bash
.venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/v1_records_test.json --profile smoke --fake-model
```

The baseline against version 1 comparison, recomputed from the committed runs. It's free, and it reproduces the committed `compare.md` exactly:

```bash
.venv/bin/python -m evals.agent_overload.compare 20261027-035635-names_only-e5cf9a5a 20261027-223042-records_retrieval-756d8701
```

Real runs call OpenAI and need `OPENAI_API_KEY` as well. Every paid command has a `--dry-run` and refuses to spend without `--confirm-spend`. The steps are in the [runbook](docs/agent-overload-experiment-runbook.md).

## 9. Hurdles

- **OpenRouter's rate limit for new accounts.** OpenRouter allows new accounts 20 requests per minute per model, which showed up while generating fixtures. The scripts now pace themselves and wait out rate-limit errors, and agent naming stops at the first delegation instead of finishing the turn. Even so, the baseline alone would have taken about 28 hours. Evaluation runs moved to OpenAI's API directly: the same model from the same provider (OpenRouter was already pinned to OpenAI), at about 75 calls per minute. Fixture generation stayed on OpenRouter.
- **Chat Completions rejected the tools.** On OpenAI directly, the Chat Completions endpoint returned HTTP 400 on every call, because it doesn't accept function tools while gpt-6-luna reasons. Runs now use the **Responses API** through a translation layer in [`harness/llm.py`](evals/agent_overload/harness/llm.py), so the production loop and its payloads stay the same. There are two side effects: `seed` is dropped (OpenAI treats it as best effort anyway), and OpenAI doesn't report cost, so run costs are estimated from list prices.
- **Time and budget.** Seven days and a $50 cap. Phases 2 and 3 of the evaluation and the scorer were cut, to leave time for the solution and a clean test run.

## 10. With more time

Roughly in priority order. The first item addresses the cost version 1 left behind.

### A scorer to cut false spawns

Version 1's duplicates happen while the right agent is in the list, so the next thing to fix is the decision to create. The scorer slot already exists ([`scorer.py`](server/services/routing/scorer.py)). It receives the message and the candidates, and returns reuse, create, ask, or "leave it to the interaction agent". Options to compare on the same frozen cases:

| Scorer | How it decides to create a new agent | Main risk |
| --- | --- | --- |
| Separate small router LLM | One cheap structured call that returns an agent ID, `NEW` or `ASK` | An extra model call on every turn |
| A yes/no question per candidate | "Does this request continue agent X's work?", with a threshold on the probability of "yes" | Needs token probabilities, which not every provider exposes |
| [TypeSafe Jev](https://docs.typesafe.ai/introduction) (through OpenRouter) | One multiple-choice question over the candidates plus `none_of_the_above`, answered with probabilities | Accuracy figures are the vendor's; the API is in alpha; an external dependency on every turn |
| Cross-encoder reranker | Scores each (request, record) pair, with a threshold tuned on labelled data | Trained for document relevance, not "the same ongoing work" |
| Embedding similarity alone | The top retrieval score has to clear a threshold | Weakest at telling similar agents apart; the floor every option must beat |
| Fine-tuned classifier | Trained on labelled (request, record, match) pairs | Needs labels first, and may overfit to synthetic data |

Any of these can also weigh record signals such as recency and usage, though leaning on recency risks locking onto the last-used agent. The scorer's answer can be a *hint* in the prompt or *enforced*, which takes routing away from the interaction agent; that choice needs its own experiment. Two cheaper levers come first: a stricter create rule in the records prompt, and a duplicate check inside `create_agent` that points at the closest existing agent. The plan is to compare the pass-through (as the control), a small router, a reranker and Jev on dev, then run the best on test once. Success means fewer false spawns and duplicates without losing version 1's accuracy.

### Archiving dormant agents

An agent unused for D days becomes `archived`; the record already has a status field for it. Archived agents are hidden from retrieval but kept: their logs stay, and they can be found and reactivated when the user comes back to their work. An agent whose trigger still runs has to count as active. The risk is that a returning user gets a duplicate, so D needs tuning on dev against the old-thread cases already in the case set, where users return to work last touched 15 to 60 days earlier.

### Capping execution agent history

Execution agents put their whole log into the prompt on every run. `ExecutionAgent` already has a `conversation_limit` that nothing sets. Capping it at the last k tasks, or summarizing older ones, would keep execution prompts bounded. This matters more after version 1, since better reuse means longer histories. The risk is a task that needs a detail from an old one, which phase 3 would measure.

### Finishing the evaluation

- **Phase 2, parallel splits:** one message that asks for several things, where each delegation has to be matched to the part of the request it serves (an LLM judge plus a maximum-weight matching).
- **Phase 3, execution:** execution agents running against a fake Gmail inbox, to measure task success against history length (with stale-fact traps), execution prompt size, and how long a batch waits for its slowest agent.
- **Real usage:** the cases are synthetic. Logs from real use would show how fast rosters actually grow and what requests really look like.

### Other gaps

- **Agents don't know what the others are doing.** Two agents can reply to the same email or set the same reminder. A shared registry of the objects agents act on (email threads, triggers), checked before any side effect, would catch it.
- **A batch waits for every agent.** Results go back to the interaction agent only when every agent in the batch has finished, with a 90-second timeout, so the slowest agent holds up the rest. Sending each result as it arrives would fix it.
- **Purposes go stale** as an agent's work drifts. They could be refreshed from recent work with one cheap call, if purposes turn out to matter.
- **Old threads under retrieval.** When a user returns to old work that isn't in the visible conversation, retrieval has only the new message to go on. A `search_agents(query)` tool is specified in the spec as a fallback.

## License

MIT, see [LICENSE](LICENSE). Based on [OpenPoke](https://github.com/shlokkhemani/openpoke) by Shlok Khemani.
