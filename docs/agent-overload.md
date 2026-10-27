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

Agreed. The metrics, and the causes each one targets, are in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md#metrics). Targets are set per solution version before its test run: version 1's are in [Decisions](#decisions) (2026-10-27).

## Candidate directions (not yet evaluated)

Each one needs: the hypothesis it addresses, its cost, its failure modes, and an experiment. Cause IDs (D1, I2, ...) refer to [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md).

### Richer agent records

Give each roster entry more than a name: a stable ID, a purpose or description, a last-active time, and a status (for example active, dormant, archived).

- Addresses: I2 (names carry too little information), I3 and I4 (routing by ID instead of by name string removes silent spawns from near-miss names and slug collisions), and lays the ground for D4 (lifecycle needs status and last-active time).
- Cost: new state in `roster.py` and a migration of `roster.json`. `send_message_to_agent` would take an ID for reuse, with a separate path for creating an agent. Someone has to write the purpose: most likely the interaction agent at creation time, which adds output tokens to that call.
- Failure modes: a purpose written at creation can be as vague as the name, and it goes stale as the agent's work drifts. Updating it means another LLM call per task. Longer entries also make the roster block bigger (I1), so on its own this may raise roster tokens per turn even if routing improves.
- Experiment: routing accuracy at fixed roster sizes with names only against names plus purpose, using the same labelled query set.
- Spec: [agent-overload-records-retrieval-spec.md](agent-overload-records-retrieval-spec.md), together with bounded retrieval.

### Bounded retrieval of candidate agents

Instead of rendering the whole roster into `<active_agents>`, retrieve a bounded set of candidates (top-k) for each interaction agent turn, for example by embedding similarity over agent purposes, and let the interaction agent choose among them or create a new one. This replaces the write-up's "semantic search over agent descriptions".

- Addresses: I1 (roster tokens become roughly constant in roster size) and D1 (the generative model sees a few options instead of all of them).
- Depends on: richer agent records, since retrieval needs something better than names to match against.
- Cost: an embedding model and an index of agent records, kept in sync as agents are created or updated. An extra retrieval step adds latency to every turn.
- Failure modes: if the right agent isn't among the k candidates, the interaction agent can't pick it and will likely create a duplicate, so retrieval misses turn into false spawns. The retrieval query is a design question: the prompt is built before the interaction agent has worked out what to delegate, so the query has to come from the incoming message (and maybe recent history), which may not name the work clearly. Agent messages and email notifications need a query too. An alternative is giving the interaction agent a search tool, which lets it form its own query but costs an extra model turn.
- Experiment: recall@k of the correct agent at roster sizes 10 to 500 on the labelled query set, then routing accuracy and false spawn rate end to end against the full-roster baseline.
- Spec: [agent-overload-records-retrieval-spec.md](agent-overload-records-retrieval-spec.md) (pinned agents + embeddings + BM25, top K, pass-through scorer slot).

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

Record each one here: setup, metric, result, conclusion.

The agreed inputs for the baseline experiment (system under test, roster sizes, metrics, labels, multi-turn design) are in [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md). Rates below come with paired or cluster-bootstrap 95% CIs in brackets; every run directory is under `evals/agent_overload/results/`.

### Phase 1 baseline: names only (2026-10-27)

- **Setup:** run `20261027-035635-names_only-e5cf9a5a`, profile `full`: today's routing (`<active_agents>` with names only), gpt-6-luna through OpenAI's API, frozen case set v1 (120 test and 60 dev single-turn cases, plus sequences), roster sizes 10 to 200, 2 reps. Cost $2.43.
- **Result (test, single-turn):**

  | N | 10 | 25 | 50 | 100 | 125 | 200 |
  | --- | --- | --- | --- | --- | --- | --- |
  | Accuracy | 84.2% | 82.5% | 76.7% | 73.8% | 73.8% | 75.4% |
  | Misroute | 1.2% | 0.0% | 12.2% | 15.2% | 12.2% | 9.8% |
  | False reuse | 55.8% | 59.6% | 48.1% | 48.1% | 53.8% | 63.5% |
  | Roster tok/turn | 309 | 792 | 1,587 | 3,216 | 4,017 | 6,363 |

  - Accuracy drop point: N = 50 on test, N = 100 on dev (dev accuracy 82.5% at N = 10, 72.5% at N = 200).
  - False spawns are near 0 at every N, and the duplicate rate in carried-forward sequences is at most 1%.
  - Roster tokens per call ≈ 10.65 × N + 154.
- **Conclusion:** hypothesis 1 (accuracy drops as the roster grows) holds: 8 to 10 points lower at N ≥ 50 than at N = 10. The main error isn't duplicates but **false reuse**: when a task needs a new agent, names only sends it to an existing one about half the time. Misroutes appear from N = 50. Hypothesis 3 (tokens grow linearly) holds.

### Version 1: records, ID routing and retrieval (2026-10-27)

Method `records_retrieval` v1 (harness 1.1.0), spec in [agent-overload-records-retrieval-spec.md](agent-overload-records-retrieval-spec.md). Dev routing runs use `dev-quick` (60 dev cases, N = 10 and 200, 1 rep) and are compared with the baseline's dev runs at the same N (2 reps). With 60 cases, only large effects are clear; McNemar slightly favours the 1-rep candidate, so the CIs carry the conclusions. Dev spend for the whole plan was $1.50.

**Purposes.** The 252 backfilled dev purposes (11 to 26 words) name the person, company or thread and often add what the name leaves out ("Riverside Aquatic Email" → "Sophie's swim lessons"). Many end with boilerplate from the first task ("without sending replies"). Not vague, so the plan went on. Purposes the model wrote through `create_agent` in the smoke run read like task instructions ("Find … and report …"); they're kept only in `raw/`, which isn't committed.

**Record size.** Smoke run `20261027-211114-records_retrieval-5bdc0131`: a record costs about 147 tokens against about 11 for a name (the spec guessed 8 times larger; it's 13.5).

**Retrieval probe** (dev, 41 reuse cases at N = 50, 100 and 200; no routing calls; one setting changed per probe):

| Probe | Change | Recall@5, all N | Recall@5, N = 200 | Recall@8, N = 200 | Recall@5, implicit follow-ups |
| --- | --- | --- | --- | --- | --- |
| `20261027-205615-probe-406ad05d` | none (defaults) | 97.6% | 97.6% | 97.6% | 100% |
| `20261027-210749-probe-9cce9d45` | pins off | 64.2% | 58.5% | 61.0% | 22.2% |
| `20261027-210819-probe-516be1cf` | BM25 off | 97.6% | 97.6% | 97.6% | 100% |
| `20261027-210856-probe-d7f6b8c9` | previous-message query off | 98.4% | 97.6% | 100% | 100% |
| `20261027-210924-probe-b1de63a8` | `w_rec` 0.5 | 98.4% | 97.6% | 97.6% | 100% |

- Pins carry retrieval: without them, 12 of 41 targets at N = 200 aren't in the top 20, and paraphrased requests reach only 59% recall@5. Most dev targets were recently active, so the probe mostly measures the pin path.
- Pinned agents are rendered first. With pins, the target is ranked first for 11% of explicit and near-distractor requests, against 74% without, which is the recency prior seen in the hand test.
- Every difference between the channel variants comes from one case (`s-dev-0034`): a switch away from the recent agent, where the previous user message pointed at the old topic.

**Hypotheses on dev:**

| ID | Runs | Result | Verdict |
| --- | --- | --- | --- |
| H1 | `20261027-213728-records_retrieval-ca5a5cd5` (every record shown) vs baseline | Accuracy +7.5 [−2.5, +17.5] at N = 10, **+19.2 [+10.0, +29.2]** at N = 200, +13.3 [+5.4, +21.3] pooled. Sequences +16.1 [+7.3, +26.6] carried, +8.9 [+4.7, +12.5] corrected. False reuse −55.8 [−72.5, −37.5]. Accuracy no longer falls with N (90.0% at 10, 91.7% at 200) | **Holds.** The gain comes mostly from CREATE cases (29% → 85% correct), not, as predicted, mainly from paraphrased queries and generic names (paraphrased 86% → 100%; only 2 generic-name units). Costs: false spawns +2.4 [0, +6.4], duplicate rate 0% → 7.7%, input tokens +75,700 per turn at N = 200 |
| H2 | `20261027-215608-records_retrieval-cdeb31cc` (K = 5, retrieval at every N) vs every record shown | Single-turn −3.3 [−10.8, +5.0] pooled, −5.0 [−15.0, +5.0] at N = 200. Sequences at N = 200 −10.4 [−16.7, −4.2] in both modes. Roster tokens per turn flat at about 2,200 (every record: 88,100 at N = 200; baseline 6,500). Against the baseline: +14.2 [+0.8, +26.7] at N = 200 | **Not rejected by its criterion**: only 1 of 21 false spawns had the target excluded. But a new failure appeared: single-turn false spawns rose to 11.0% [2.5, 21.2] (baseline 0.0%) and the duplicate rate to 15 to 21%, with the target **shown first** in 18 of 21 false spawns. Cause unknown |
| H3 | Probes above | Recall@5 on implicit follow-ups 100% with pins, 22.2% without (9 cases × 3 sizes) | **Holds** |
| H4 | `20261027-220052-records_retrieval-2720a158` (no purposes) vs H2's run | Accuracy 0.0 [−4.2, +4.2] pooled, +3.3 [−5.0, +11.7] at N = 10, −3.3 [−10.0, +3.3] at N = 200 | **Rejected on dev**: no worse without purposes. Tested with retrieval only; a small effect can't be ruled out, and recent work repeats the first task the purpose was written from |

**K = 8 diagnostic** (`20261027-220957-records_retrieval-600b94f5`). Question: does a longer list stop the false spawns? Rule set before the run: K = 8 replaces K = 5 if its false-spawn rate (single and sequence turns pooled) is at most half of K = 5's and accuracy isn't lower. Result: 9.4% against 10.4% (every record shown 3.5%, baseline 0.2%), accuracy 88.1% against 87.2%. Single turns improved at N = 10 (+10.0 [+3.3, +18.3]) and corrected sequences got worse (−6.2 [−10.4, −2.1]). **List length isn't the cause; K stays 5.** The cause of retrieval false spawns is an open question for version 1.1.

**Chosen parameters** (rules in [Decisions](#decisions), 2026-10-27): K = 5, `full_roster_max` 50, BM25 on, previous-message query off, `w_rec` 0, pins on (at most 3), purposes backfilled.

**Test run** (`20261027-223042-records_retrieval-756d8701`, frozen config `v1_records_test.json`, run once; cost $2.14). Compared with the baseline's test split by `compare.py` (`results/comparisons/20261027-035635-names_only-e5cf9a5a__vs__20261027-223042-records_retrieval-756d8701/`).

| N | 10 | 25 | 50 | 100 | 125 | 200 |
| --- | --- | --- | --- | --- | --- | --- |
| Accuracy, baseline | 84.2% | 82.5% | 76.7% | 73.8% | 73.8% | 75.4% |
| Accuracy, version 1 | 91.2% | 95.0% | 91.2% | 84.6% | 85.4% | 85.4% |
| Difference | +7.1 [+1.7, +12.9] | +12.5 [+6.2, +18.8] | +14.6 [+7.9, +22.1] | +10.8 [+2.5, +19.2] | +11.7 [+3.7, +20.0] | +10.0 [+1.7, +17.9] |
| Roster tok/turn, baseline | 309 | 792 | 1,587 | 3,216 | 4,017 | 6,363 |
| Roster tok/turn, version 1 | 4,320 | 10,797 | 21,657 | 2,184 | 2,211 | 2,193 |
| False spawn, version 1 | 4.3% | 1.8% | 3.7% | 14.6% | 10.4% | 12.8% |
| Duplicate rate (carried sequences), baseline → version 1 | 0.0% → 12.5% | n/a | 0.0% → 25.2% | 1.0% → 29.5% | 0.0% → 25.3% | 1.0% → 26.4% |

- **T1 passes.** Single-turn accuracy +11.1 points [+5.6, +16.9] pooled over N (88.8% against 77.7%; McNemar p = 3.5e-8: 133 case-size units right only with version 1 against 57 only with the baseline), and the CI is above 0 at every N. False reuse fell by 46.2 points [−59.7, −33.8] and misroutes by 8.1 [−12.3, −4.5].
- **T2 passes.** Roster tokens per turn at N = 100, 125 and 200 are 32%, 45% and 66% below the baseline, and flat in N. All input tokens per turn are 370, 1,270 and 3,340 lower there. At N ≤ 50, where every record is shown, input tokens per turn are 4,100 to 18,900 higher, as expected.
- **Duplicates (reported, not a target) are the cost.** False spawns on reuse turns, single and sequence together: 15.4% (337 of 2,184) against 0.4%. At the end of carried-forward sequences, 12.5% to 29.5% of agents are duplicates (inflation ratio 1.16 to 1.47) against at most 1%. They happen with every record shown too (N = 10 and 50), in both sequence modes, and for every query style, including explicit requests. Retrieval misses explain only 28 of the 337; in 111 the target was shown first.
- **Sequences show no accuracy gain:** +2.7 [−5.0, +9.1] carried forward, −0.8 [−5.6, +3.2] corrected. The fewer false reuses and misroutes are offset by false spawns (+24.0 [+19.0, +29.3] carried forward).
- The accuracy drop point moved from N = 50 to N = 100 (−6.7 [−12.9, −0.8] from N = 10), which is where retrieval takes over, and accuracy at N = 200 stays 10 points above the baseline's.

**Conclusion.** Version 1 meets both targets: routing is more accurate at every roster size, and above 50 agents the interaction agent sees a smaller, constant roster block. It doesn't solve agent overload yet. It creates a new agent for work an existing agent owns about 15% of the time, so in multi-turn use the roster grows about 1.2 to 1.5 times faster than the work requires, which feeds the problem it set out to fix. The baseline's error (reusing the wrong agent for new work) has largely been traded for this one. Version 1.1 should target false spawns: the model creates agents while the right one is listed, so the likely levers are the records prompt's create rule and the `create_agent` decision itself (for example a scorer that has to rule out the listed candidates first), not retrieval.

## Decisions

- **2026-10-25: Metrics agreed.** The primary, secondary and guardrail metrics in [agent-overload-causes-and-metrics.md](agent-overload-causes-and-metrics.md#metrics) are what solutions will be judged against. Targets are set after a baseline is measured.
- **2026-10-25: Baseline experiment scope.** Roster sizes 10, 25, 50, 100, 125 and 200, names only as in today's code. Metrics measured first: routing accuracy, roster tokens per turn, duplicate rate, execution task success against history length, and batch latency (execution task success moved up to primary). Single-delegation cases first, then parallel-split cases. No new integrations before the baseline. Details in [agent-overload-baseline-experiment.md](agent-overload-baseline-experiment.md).
- **2026-10-27: Version 1 test targets.** Agreed before the version 1 test run, which is compared with baseline `20261027-035635-names_only-e5cf9a5a` on the test split:
  - **T1, accuracy gain:** single-turn suite, version 1 minus baseline accuracy pooled over all roster sizes. Passes if the paired 95% CI of the difference is above 0.
  - **T2, fewer tokens shown to the interaction agent:** `<active_agents>` tokens per turn at N = 100, 125 and 200, where retrieval runs. Passes if lower than the baseline at all three. At N ≤ 50 the config shows every record, so those tokens are higher by design: a record costs about 147 tokens against about 11 for a name (smoke run `20261027-211114-records_retrieval-5bdc0131`).
  - **Reported, not pass/fail:** false-spawn rate and duplicate rate. On dev, retrieval raised false spawns from 0.2% (baseline) to about 10%, and duplicates make the roster grow. Passing T1 and T2 shows more accurate routing and a cheaper roster block; it doesn't by itself show the overload problem is solved.
- **2026-10-27: Version 1 test config frozen** (`evals/agent_overload/configs/v1_records_test.json`, copied into `RetrievalParams` so `make dev ROUTING=records` runs it). Every value was chosen on dev; the evidence is in [Experiments](#experiments).
  - `full_roster_max` 50: the largest N in the baseline's dev sweep below its dev accuracy drop point (N = 100), per the spec's rule.
  - K = 5: the smallest of {5, 8, 12} with dev recall@K ≥ 0.95 at N = 200 (0.976, 40 of 41). A K = 8 diagnostic for retrieval false spawns missed its pre-set rule (false spawns at most half of K = 5's: 9.4% against 10.4%), so K stayed 5.
  - BM25 on and `w_rec` 0: ties with the alternative at K, kept at the defaults. `w_rec` 0.5 also lowered recall@3 (95.1% to 88.6%) and adds recency-lock risk on top of pins.
  - Previous-user-message query off: never worse at any k, and it recovered the one topic-switch miss. This matches the hand test, where it added noise on topic switches.
  - Pins on, at most 3: H3 holds on dev (recall@5 on implicit follow-ups 100% with pins against 22% without).
  - Purposes kept (`seed_purposes` "backfill"), although H4 was rejected on dev: that run used retrieval only, so purposes were never tested with every record shown (N ≤ 50 in this config), and the product writes them through `create_agent` anyway.
