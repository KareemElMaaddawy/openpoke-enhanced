# Agent overload: experiment runbook

How to run phase 1 of the agent overload experiment, step by step: build the frozen case set, run the smoke check, run the baseline, read the report, and later compare a new routing method against the baseline. The design behind every step is in [agent-overload-experiment-design.md](agent-overload-experiment-design.md); results go into the Experiments section of [agent-overload.md](agent-overload.md).

Every command runs from the repository root. Commands that call a paid API are marked **Paid**. The implementing agent never runs those; the user runs each one by hand.

## At a glance

| # | Step | Script | Paid | Estimated cost | Estimated time |
| --- | --- | --- | --- | --- | --- |
| 0 | Setup and free checks | `make setup`, unit tests | no | $0 | 5 min |
| 1 | Thread specs and chit-chat | `generation/gen_threads.py` | Sonnet 5.5 | **$2.35 actual** (est. $1.54) | about 4 min |
| 2 | Agent names, filler cleaning, rosters | `generation/name_agents.py` | gpt-6-luna | $0.46 | first run took hours; now stops at the first delegation, about 50 min for all 585 threads at 18 requests/min (guess) |
| 3 | Name ratings | `generation/rate_names.py` | Sonnet 5.5 | $0.31 | 1 min |
| 4 | Single-turn cases | `generation/draft_cases.py` | Sonnet 5.5 | $5.00 | 8 to 15 min |
| 5 | Sequences | `generation/draft_sequences.py` | Sonnet 5.5 | $0.83 | 1 to 3 min |
| 6 | Long histories | `generation/assemble_histories.py` | no | $0 | seconds |
| 7 | Frozen summaries | `generation/summarize_histories.py` | gpt-6-luna | $0.07 | 1 to 2 min |
| 8 | Second labels | `generation/cross_label.py` | Gemini 3.8 Flash | $2.68 | 5 to 10 min |
| 9 | Label review (agent, then user) | `generation/build_review.py` | no | $0 | ≤ 30 min of your time |
| 10 | Freeze | `generation/freeze.py` | no | $0 | seconds |
| 11 | Smoke run | `run.py --profile smoke` | gpt-6-luna (OpenAI API) | $0.13 | a few minutes |
| 12 | Baseline | `run.py --profile full` | gpt-6-luna (OpenAI API) | about $5 | about 2.5 to 3 h at 75 requests/min (estimate) |

Fixtures total about $11.90 (step 1 actual plus the other steps' estimates), plus about $8 for the baseline. Step 1 used about 1.75 times the output tokens estimated, so steps 4 and 5 were re-estimated on 2026-10-26 with that factor. Costs are the `--dry-run` estimates before any margin. Times are guesses until the first steps have run. Each paid step stops on its own at twice its estimate, and no step starts if the ledger total plus its estimate × 1.25 would pass $50.

## How spending is guarded

Every paid command (each generation script that calls a model, and `run.py`) behaves the same way:

- **`--dry-run`** prints the planned calls, the models, the estimated cost, the ledger total and the per-run cap, then exits without calling any API. Run it first, every time.
- **Without `--confirm-spend`** the command prints the same summary and exits with code 2. Nothing is called.
- **With `--confirm-spend`** it refuses to start (exit 3) if the ledger total plus the estimate × 1.25 would pass the $50 total cap. Otherwise it runs, and stops cleanly when its own spend reaches the per-run cap: twice the estimate for generation steps, `budget.max_cost_usd` ($10) for `run.py`. Override either cap with `--max-cost <usd>`.
- **The ledger.** Every real run and fixture step appends its actual cost (from OpenRouter's `usage.cost`) to `evals/agent_overload/results/spend_ledger.jsonl`, even if it fails or is capped. The ledger total is the source of truth for the $50 budget.
- **`--fake-model`** runs the same code against a deterministic fake model: no API calls, nothing written to the ledger. That's how the code was tested.
- **A second guard outside the harness:** the dedicated OpenRouter key with a $50 credit limit (see Setup).

Generation steps are **resumable**: each saves what it finished, even when capped or interrupted. Rerunning the same command does only the missing work.

## Rate limits

OpenRouter limits new accounts to **20 requests per minute per model** (an HTTP 429 says `new-account-rpm`; seen on 2026-10-26). Every paid command therefore paces itself: at most `--rpm` requests start in any minute for each model (default 18), and a 429 pauses that model's calls until the reset time OpenRouter reports. Each dry run prints the minimum time this implies. Once the limit is lifted, `--rpm 0` turns pacing off. The pacing wait isn't counted in measured latency.

**Runs (`run.py`) call OpenAI's API directly** (`models.api: "openai"` in the config, decided 2026-10-27): at 18 requests per minute the baseline would have taken about 28 hours. OpenAI's Tier 1 limit for gpt-6-luna is 500 requests and 500,000 tokens per minute (model page, 2026-10-27). At about 6,100 prompt tokens per call the token limit binds near 80 calls a minute, so `run.py` paces at 75 by default. Check your account's limits page: on a higher tier, pass a higher `--rpm`. A 429 waits for the reset OpenAI reports; a 429 for `insufficient_quota` (out of credit) stops the call at once. Generation scripts (steps 1 to 8) still go through OpenRouter.

## 0. Setup

1. Install dependencies, if you haven't already. This creates `.venv/` and installs `server/requirements.txt`; the harness needs nothing else.

   ```bash
   make setup
   ```

2. **Create a dedicated OpenRouter key for the experiment** with a credit limit of $50 (OpenRouter → Settings → API Keys → Create key → set the credit limit). Use it only for this experiment, so the provider enforces the budget too.

3. Make the key available as `OPENROUTER_API_KEY`, either in `.env` at the repository root (`server/config.py` reads it) or exported in the shell you run the commands from. A shell export wins over `.env`.

4. **For runs (steps 11 and 12 and later methods), add an OpenAI API key** as `OPENAI_API_KEY`, in the same `.env` or exported. `run.py` sends calls straight to OpenAI (see [Rate limits](#rate-limits)). Your OpenAI organization needs prepaid credit (Tier 1 starts after the first $5). On the OpenAI platform, set a monthly budget for the project the key belongs to, so the provider enforces a limit too.

5. Confirm the keys are visible without printing them:

   ```bash
   .venv/bin/python -c "from server.config import get_settings; import os; print('openrouter key set:', bool(get_settings().openrouter_api_key), '| openai key set:', bool(os.environ.get('OPENAI_API_KEY')))"
   ```

6. Run the free test suite (no API calls; about 10 seconds):

   ```bash
   .venv/bin/python -m unittest discover -s evals/agent_overload/tests -t .
   ```

   All tests must pass. They include a full fake-model run of every step below.

7. Work on a clean, committed tree. `run.py` refuses to run on uncommitted code or fixtures (`--allow-dirty` overrides it, and the report flags that). Run outputs under `evals/agent_overload/results/` don't count as dirty.

If your virtual environment is somewhere else, replace `.venv/bin/python` with its Python in every command.

## Fixture generation (steps 1 to 10)

The steps build `evals/agent_overload/fixtures/v1/` in order; each needs the previous one's output. After every step, check its output before starting the next one. `inspect_fixtures` (free) prints counts and samples:

```bash
.venv/bin/python -m evals.agent_overload.generation.inspect_fixtures all
```

Until step 10 the directory is a work in progress. Once `MANIFEST.json` exists the set is frozen, and every generation script refuses to touch it.

### Step 1. Thread specs and chit-chat (Paid: Sonnet 5.5)

Writes the world the cases are built from: per split, about 110 (test) or 55 (dev) case threads, including 30 or 15 near-distractor pairs, plus 210 filler threads, across 12 categories. It also writes the pool of about 60 small-talk exchanges and 15 acknowledgements used to pad long histories. The 12 categories run in parallel. Within a category, test then dev, case then filler, each batch is told the topics already written, so the splits share nothing.

- **Estimated cost and time:** $1.54 at first; the first run cost $2.35 (about 1.75 times the output tokens estimated, plus 6 retries) and took about 4 minutes. The script's estimates now use the measured token counts.
- **Writes:** `fixtures/v1/threads.dev.jsonl`, `threads.test.jsonl`, `chitchat.jsonl`, and every batch's parsed output in `review/gen_threads/`.

```bash
.venv/bin/python -m evals.agent_overload.generation.gen_threads --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.gen_threads --confirm-spend
```

**Check before moving on**

- The last lines say `threads written: {'dev': 265, 'test': 320}`.
- `inspect_fixtures threads`: 55 + 210 (dev) and 110 + 210 (test) threads, 15 and 30 pairs. In the samples, topics name concrete entities, requests read like texts, and each pair looks alike but is clearly different work.
- `chitchat` shows about 60 exchanges and 15 acks, with no tasks in them.

**If it fails or is capped**

- A batch that fails validation three times is reported as `error: ...`. Rerun the same command; only the missing batches are retried.
- If it's capped, compare the actual cost with the estimate before rerunning (the output tokens per batch may be higher than assumed). Rerun with `--max-cost` set a little above what's left to do.

### Step 2. Agent names, filler cleaning and rosters (Paid: gpt-6-luna)

For each of about 585 threads, runs the **real** interaction prompt (production system prompt, tool schemas and loop, the pinned model, OpenAI as the only provider) with an empty roster and history and the thread's opening request as the new message. It keeps the name of the first agent the model creates, and stops the loop there. Turns with no delegation, and names that match or slug-collide with one already taken, are resampled with a new seed, up to 3 attempts; then the thread is dropped. Attempts that fail with an API error (a 429 after its retries, say) don't count toward the 3; the thread is tried again, and if API errors persist it stays pending for the next rerun. Then it removes filler agents whose names resemble a case agent's, trims filler to 200 per split, and writes each split's fixed filler order and filler ages (30% 0 to 3 days, 30% 4 to 14, 40% 15 to 60).

- **Estimated cost and time:** $0.46 (cap $0.93) when it ran the whole loop. It prints progress every 40 threads. The first attempt on 2026-10-26 hit the rate limit and was stopped after naming 24 dev threads ($0.06); the rerun named the rest over several hours. Cleaning rule v1 then left 126 dev and 100 test filler, so the rule changed (v2) and naming now stops at the first delegation; see the design's decisions table. On those names v2 keeps 175 dev and 165 test, so the first run needs one top-up per split: 43 dev, 61 test.
- **Writes:** `agents.dev.jsonl`, `agents.test.jsonl`, `rosters.dev.json`, `rosters.test.json`, `review/naming/<split>.json` (every attempt), `review/filler_cleaning.<split>.json`.

```bash
.venv/bin/python -m evals.agent_overload.generation.name_agents --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.name_agents --confirm-spend
```

**Check before moving on**

- It prints one line per split, for example `test: 110 case agents, 200 filler, N filler removed, M threads dropped`. Dropped threads should be a handful at most.
- `inspect_fixtures agents`: names look like names the interaction agent writes ("AWS Invoice Lookup", "Email to Keith"). Most threads are named on the first attempt.
- No `warning:` lines. The pin check passed, or the command would have stopped before calling anything.
- Filler threads whose topic duplicates a case thread (step 1 produced one: `t-dev-0331` repeats `t-dev-0019`, a Costco tire appointment) should have been removed by name cleaning; the agent checks this.

**If it fails or is capped**

- `warning: <split>: only N filler agents after cleaning` means cleaning removed more than 10. Top up by the number the warning prints (the shortfall over the split's observed yield, plus 25%) and rerun this step; only the new threads get named. The top-up runs in batches of 20:

  ```bash
  .venv/bin/python -m evals.agent_overload.generation.gen_threads --top-up-filler 61 --split test --confirm-spend
  ```

  ```bash
  .venv/bin/python -m evals.agent_overload.generation.name_agents --confirm-spend
  ```

- `Refusing: model pin check failed` means `openai/gpt-6-luna` no longer resolves to `openai/gpt-6-luna-20260922`. Stop and decide with the agent; `--accept-model-change` exists but changes the system under test.
- Capped or interrupted: rerun; finished threads are kept in `review/naming/`.

### Step 3. Name ratings (Paid: Sonnet 5.5)

Rates every agent name as `specific` (names the entity and the task), `partial` (one of the two) or `generic` (neither), 40 names per call. Whatever mix comes out is reported, not forced. It's used for the "name descriptiveness" breakdown.

- **Estimated cost and time:** $0.31 (cap $0.61); about a minute.
- **Writes:** `descriptiveness` in `agents.<split>.jsonl`, and the mix in `review/name_ratings.json`.

```bash
.venv/bin/python -m evals.agent_overload.generation.rate_names --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.rate_names --confirm-spend
```

**Check before moving on:** the printed mix covers every case agent (no `unrated`), and a few spot checks in `inspect_fixtures agents` look right. **If it fails:** rerun; only unrated agents are sent again.

### Step 4. Single-turn cases (Paid: Sonnet 5.5)

Code plans all 180 cases first, so the quotas are exact: the label, query style, message type, short or summarized history, the target's roster position, old-thread cases, which threads appear and in what order, the case's timestamp and agent ages. Sonnet then writes only the text: the end of the conversation and the new message, following the labeling rules. Code checks each draft against its plan (threads used, order, forbidden names, 4 to 16 entries), renders the result lines with the exact frozen agent names, and assigns timestamps. A rejected draft is redrafted, up to 3 attempts.

- **Estimated cost and time:** $5.00 (cap $9.99); 8 to 15 minutes.
- **Writes:** `cases.single.dev.jsonl`, `cases.single.test.jsonl`, and `review/draft_failures.jsonl` for cases that failed all attempts.

```bash
.venv/bin/python -m evals.agent_overload.generation.draft_cases --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.draft_cases --confirm-spend
```

**Check before moving on**

- `dev: 60 cases drafted` and `test: 120 cases drafted`, with no failures reported.
- `inspect_fixtures cases`: the quota cells match the design (for example `REUSE/explicit` 18 on test, 9 on dev). The sampled histories read naturally, and each message plausibly has the planned label.

**If it fails or is capped:** rerun the same command; only missing cases are drafted. If the same cases keep failing, look at the reason in `review/draft_failures.jsonl` and tell the agent: it usually means the plan is hard to write naturally.

### Step 5. Sequences (Paid: Sonnet 5.5)

Code plans 8 test and 4 dev sequences of 12 turns each: three seeded threads, a near-distractor pair, and two threads created during the run. The turn mix is 2 CREATE, at least 6 REUSE (including an implicit follow-up right after a topic switch, and a near-distractor), 1 REUSE_ANY and at least 2 NO_DELEGATION, with at least one email alert and frequent topic switches. Sonnet writes each turn's message and the gold replies and results.

- **Estimated cost and time:** $0.83 (cap $1.65); 1 to 3 minutes.
- **Writes:** `cases.sequence.dev.jsonl`, `cases.sequence.test.jsonl`. The two created threads' agents are marked `"seeded": false` in `agents.<split>.jsonl`; their frozen names are the gold names for corrected-each-turn runs.

```bash
.venv/bin/python -m evals.agent_overload.generation.draft_sequences --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.draft_sequences --confirm-spend
```

**Check before moving on:** `dev: 4 sequences drafted`, `test: 8 sequences drafted`. In `inspect_fixtures sequences`, the sample reads like a few days of real use, and each turn fits its label. **If it fails:** rerun.

### Step 6. Long histories (free)

Builds long histories in code from the threads' own requests and results plus the chit-chat pool, in the same four-entry shape production logs (request, acknowledgement, `[SUCCESS] <agent>: <result>`, reply). Summarized single-turn cases get 100 to 126 entries in front of their drafted tail, so the raw history has at least 110. Sequences get 96 entries before turn 1, so the real summarizer runs during each sequence. The output is deterministic.

```bash
.venv/bin/python -m evals.agent_overload.generation.assemble_histories --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.assemble_histories
```

- **Writes:** `review/raw_histories/<case_id>.jsonl` for the 54 summarized cases, and `initial_history` in the sequence files.
- **Check:** `dev: assembled 18 summarized single-turn histories and 4 sequence histories`, and 36 and 8 for test.

### Step 7. Frozen summaries (Paid: gpt-6-luna)

Applies the production summarization rule once to each of the 54 long histories. The first 100 entries go through the real `build_summarization_prompt` and the pinned summarizer model. The case keeps the summary, `last_index` 99, and the remaining entries, always including the drafted tail.

- **Estimated cost and time:** $0.07 (cap $0.14); 1 to 2 minutes.
- **Writes:** `summary_text`, `last_index` and the remaining entries in `cases.single.<split>.jsonl`.

```bash
.venv/bin/python -m evals.agent_overload.generation.summarize_histories --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.summarize_histories --confirm-spend
```

**Check:** `dev: 18 histories summarized`, `test: 36 histories summarized`, no warnings. Open one summarized case and confirm the summary follows the production format ("Summary generated: ...", "Timeline & Commitments:", ...). **If it fails:** rerun; only unsummarized cases are sent.

### Step 8. Second labels (Paid: Gemini 3.8 Flash)

A model from a different family than both the drafter (Anthropic) and the system under test (OpenAI) labels every single-turn case and every sequence turn blind. It gets the labeling rules and exactly what the interaction agent would see at N=200, without the draft's label. Sequences are labeled turn by turn from the gold state, with one real summarizer call per sequence once the history crosses the threshold.

- **Estimated cost and time:** $2.68 (cap $5.36); 5 to 10 minutes.
- **Writes:** `provenance.cross_label` on every case and turn, and `review/cross_label_summary.json`.

```bash
.venv/bin/python -m evals.agent_overload.generation.cross_label --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.generation.cross_label --confirm-spend
```

**Check before moving on**

- The `agreement:` line shows, per split, how many items were labeled and how many agree, plus `invalid` (answers that couldn't be parsed). `invalid` should be 0 or close to it.
- Agreement of 75 to 90% is a healthy range (a guess; there's no baseline for it). **Below about 60%, stop and tell the agent**: that points at the rules or the drafts, not at individual cases.
- `inspect_fixtures labels` shows which label kinds the disagreements fall in.

**If it fails:** rerun. `--only s-test-0007,q-test-003` relabels specific cases, for example after a redraft.

### Step 9. Label review

The goal is trustworthy labels for no more than about 30 minutes of your time. The agent handles every disagreement first, and you see only the items the agent is unsure about, plus 10 random agreed items as a sanity check.

**9a. List the disagreements** (free; the agent or you):

```bash
.venv/bin/python -m evals.agent_overload.generation.build_review disagreements
```

This writes `review/disagreements.md`. The agent reads each item, applies the labeling rules, and records one decision per item in `review/agent_decisions.jsonl`: keep the draft, use the second label, relabel, rewrite the case to remove the ambiguity, drop it (single-turn only; it gets redrafted), or mark it unsure. Each decision comes with a one-line rationale.

**9b. Build your queue** (free):

```bash
.venv/bin/python -m evals.agent_overload.generation.build_review sheet
```

This applies the agent's decisions and writes `review/review_sheet.md` (what to read) and `review/user_decisions.json` (where to answer). It refuses if the queue would pass 30 items; the agent then drops the most ambiguous items and they're redrafted (9e) instead of reviewed.

**9c. Review** (you): open `evals/agent_overload/fixtures/v1/review/review_sheet.md`. Each item shows the visible history, the new message, the agents involved, both labels and the agent's note. Decide each one under the rules in `generation/prompts/labeling_rules.md`, and fill in `decision` for each item in `review/user_decisions.json`:

- Unsure items: `"draft"` (the draft label is right), `"labeler"` (the second label is right), `"label"` (neither: set `"label": {"kind": "REUSE", "agents": ["<exact agent name>"]}`, or kind `REUSE_ANY` with several names, or `CREATE` with `"new_thread": "<thread id>"`, or `NO_DELEGATION`), or `"drop"` (the case is too ambiguous to keep).
- Sanity items: `"ok"` or `"wrong"` (if wrong, also set `label`).
- `note` is optional.

**9d. Apply your decisions** (free):

```bash
.venv/bin/python -m evals.agent_overload.generation.build_review apply
```

It prints how many sanity items were wrong. If more than 1 of the 10 is wrong, review 20 more agreed items together with the agent before freezing:

```bash
.venv/bin/python -m evals.agent_overload.generation.build_review sheet --extra-sanity 20
```

**9e. Redraft dropped cases** (Paid, only if cases were dropped). The plain command drafts any missing case; then rebuild its history and label it again:

```bash
.venv/bin/python -m evals.agent_overload.generation.draft_cases --confirm-spend
```

```bash
.venv/bin/python -m evals.agent_overload.generation.assemble_histories
```

```bash
.venv/bin/python -m evals.agent_overload.generation.summarize_histories --confirm-spend
```

```bash
.venv/bin/python -m evals.agent_overload.generation.cross_label --confirm-spend
```

Then repeat 9a to 9d for the new items only.

Every decision is stored in the case's `provenance.review` as `{"by": "agent" | "user", ...}`.

### Step 10. Freeze (free)

Validates everything and computes the derived fields:

- `meta.prev_thread`, `meta.target_name_visible`, `meta.name_descriptiveness` and `meta.target_age_bucket`.
- `agent_times`, from the latest result line naming each agent (including the summarized part) or from `agent_ages`.

It then checks the quotas and rules: old-thread targets are 15 to 60 days old and absent from the visible history, every disagreement has a decision, and so on. Finally it writes `MANIFEST.json` with every file's hash and the `case_set_hash`, and puts the hash into the run config.

```bash
.venv/bin/python -m evals.agent_overload.generation.freeze --check
```

```bash
.venv/bin/python -m evals.agent_overload.generation.freeze --update-config
```

- **Check:** `--check` prints the quota report and `check passed`. The real run prints `frozen: case_set_hash <hash>` and `updated .../baseline_names_only.json`.
- **If `--check` lists problems:** fix them (usually a missing review decision, or a dropped case that wasn't redrafted) and run it again. `--allow-quota-gaps` freezes with a short quota cell, and records that in the manifest; use it only if you've agreed on it.
- **Then commit** the fixtures and the config. `run.py` refuses a dirty tree, and the frozen set is part of what results are compared on:

  ```bash
  git add evals/agent_overload/fixtures/v1 evals/agent_overload/configs/baseline_names_only.json && git commit -m "evals: freeze agent overload case set v1"
  ```

After freezing, the harness verifies every file's hash when it loads the set and refuses to run if one byte has changed. Changing anything means a new version directory (`fixtures/v2/`) and a new hash.

## 11. Smoke run (Paid: gpt-6-luna)

Checks the whole harness against the real model before the expensive run, on a small slice: dev split, N = 10 and 200, 1 rep, 10 single-turn cases picked across the label and style cells, 1 sequence in both modes, and token probes. It also measures the real calls, tokens and cost per turn, which later pre-run estimates use in place of the design's guesses.

- **Estimated cost and time:** $0.13; a few minutes. 68 turns, about 160 calls. The first smoke run (2026-10-27, `20261027-023444-names_only-8ec89b24`, through OpenRouter) took 25 minutes and 468 calls: gpt-6-luna kept calling `wait` after delegating, and 52 of 68 turns hit the loop limit. The interaction loop now ends a turn at a wait-only response (see the design's decisions), so rerun it on OpenAI direct before the baseline.
- **Writes:** `evals/agent_overload/results/<run_id>/` (see [What a run writes](#what-a-run-writes)), and a line in `spend_ledger.jsonl`.

```bash
.venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/baseline_names_only.json --profile smoke --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/baseline_names_only.json --profile smoke --confirm-spend
```

**Check before moving on.** Open `results/<run_id>/report.md`.

- **Section 1:** no warnings except, possibly, the dirty-tree flag if you passed `--allow-dirty`. `Providers seen` is only OpenAI. api_error is 0.
- **Section 10, price check:** close to 1.0, which means `order: ["openai"]` lands on the standard endpoint. Well below 1 suggests the flex endpoint, well above suggests the fast one; in either case the config must pin the standard endpoint before the baseline.
- **Section 7, tokens:** roster tokens per call are not `n/a`. If they are, the token probe (one call with `max_tokens: 1`) was rejected; check the error in `turns.jsonl.gz` and tell the agent.
- **Section 8:** the invalid call rate and the loop-limit count.
- **Measured per-unit costs** (end of section 10) against the design's estimates: $0.0014 per single-turn turn, $0.0020 per sequence turn, 2.2 routing calls per turn.

Then tell the agent the run id. At checkpoint D the agent compares these numbers with the design's estimates, updates the cost section and this runbook, says whether the baseline still fits the budget, and reports how gpt-6-luna handles the prompt's reply-then-delegate flow.

**If it fails:** a non-zero exit code means it stopped for a reason it printed (see [Exit codes](#exit-codes)). If it's capped (which it shouldn't be at $10), don't continue: something costs far more than estimated.

## 12. Baseline (Paid: gpt-6-luna)

The full phase 1 baseline: both splits, every roster size (10, 25, 50, 100, 125, 200 for single-turn cases; sequences at 10, 50, 100, 125, 200 on test and 10, 200 on dev), 2 reps, both sequence modes, and token probes.

- **Estimated cost and time:** $7.86 from the design's estimates; after the smoke run, the dry run uses the smoke run's measured costs instead (only smoke runs with the same `models.api` count). At OpenAI's Tier 1 limit, about 2.5 to 3 hours (estimate: about 2.75 calls per turn after the wait fix, at 75 per minute; see [Rate limits](#rate-limits)).
- **Writes:** `results/<run_id>/`, a line in `spend_ledger.jsonl`, and a line in `test_ledger.jsonl`, since it includes the test split.

```bash
.venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/baseline_names_only.json --profile full --dry-run
```

```bash
.venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/baseline_names_only.json --profile full --confirm-spend
```

**Before running:** read the dry run. If it shows `WARNING: estimate x margin ... is above the per-run cap`, the measured costs are higher than the design assumed and the run would likely be capped (a capped run can't be used for comparisons). Pass the suggested `--max-cost`, after checking that the ledger total plus the estimate still fits the $50 budget. Commit first: the run refuses a dirty tree.

**Check after it finishes**

- Exit code 0, and no warnings in section 1 of the report.
- api_error under 2% (the run is marked FAILED above that).
- The cost in the ledger is close to the estimate.

Then commit the results (`results/<run_id>/` without `raw/`, which is ignored, plus both ledgers) and tell the agent the run id.

**If it fails or is capped:** a capped or failed run can't be used for comparisons, and the baseline must be rerun after fixing the cause. Rerunning `full` with the same config is allowed by the test ledger, because the config hash doesn't change. Check the ledger total against the budget first.

## Reading `report.md`

Every run writes `evals/agent_overload/results/<run_id>/report.md`. The sections:

1. **Run identity:** run id, method, case set hash, model (and the slug it resolved to), providers seen, git SHA, and warnings (dirty tree, model change, cap, api errors, fake model).
2. **Headline:** one row per roster size N, from the single-turn suite on the test split (dev if a run has no test split). Each cell is the value with its 95% confidence interval (a cluster bootstrap over cases).
3. **Accuracy drop point:** the smallest N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0. It's the "N" for "retrieval only above N". "None detected" means accuracy held up across the sizes tested.
4. **Confusion matrices** at the smallest and largest N: rows are the correct label kinds, columns what the model actually did.
5. **Breakdowns:** accuracy per query style, message type, label kind, target position, target age, name descriptiveness, history type and whether the target's name is visible, one row per N.
6. **Sequences:** accuracy carried forward against corrected each turn, compounding by turn index, recency lock, and the duplicate statistics.
7. **Tokens:** roster tokens per call and per turn against N, and the tokens-per-agent slope.
8. **Consistency, invalid calls, loop limits:** how often the reps agree, and how often the model made malformed tool calls.
9. **Dev split:** the same headline table for dev.
10. **Costs:** total cost, calls by purpose, the price check and the measured per-unit costs.

Headline columns:

| Column | Meaning |
| --- | --- |
| Accuracy | Share of turns routed exactly right: reused the thread's original agent, correctly created one, or correctly didn't delegate, with no extra delegation |
| False spawn | Of turns that should reuse an agent: the model created a new one instead (the duplicate-making error) |
| Misroute | Of turns that should reuse an agent: the model sent the work to the wrong existing agent |
| False reuse | Of turns that should create an agent: the model reused an existing one |
| Missed deleg. | Of turns that should delegate: the model didn't delegate at all |
| Extra deleg. | Share of turns with a delegation beyond the one expected |
| Duplicate rate | From carried-forward sequences: share of agents at the end of a sequence that duplicate another agent of the same thread |
| Roster tok/turn | Tokens spent on the `<active_agents>` block per turn: prompt tokens at N minus the same prompt with an empty roster, times the routing calls in the turn |
| Input tok/turn | All prompt tokens of the routing method's calls in the turn (median) |
| Cost/turn | Mean cost of the routing method's calls per turn (a guardrail) |
| Latency p50 | Median total model time per turn, at the configured concurrency |

The full numbers, including every CI and breakdown, are in `metrics.json`.

## Rerunning for a later method and comparing

A later routing method (for example richer records with retrieval) is compared against this baseline on the same frozen cases:

1. Implement it as a class in `evals/agent_overload/harness/methods/` that follows `RoutingMethod` in `methods/base.py`, and register it in `make_method` in `run.py`.
2. Copy `configs/baseline_names_only.json` to a new config (for example `configs/v1_records_retrieval.json`) and change only `method` (`name`, `version`, `params`). Keep the case set, models, sizes, reps and stats the same: comparisons need identical settings.
3. Iterate on dev only: `--profile dev-quick` (about $0.50) for fast checks, and `--profile dev` (about $2) before the test run. Tuning anything (prompts, thresholds, k) on test isn't allowed.
4. Run test **once** per method version:

   ```bash
   .venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/<new_config>.json --profile test --dry-run
   ```

   ```bash
   .venv/bin/python -m evals.agent_overload.run --config evals/agent_overload/configs/<new_config>.json --profile test --confirm-spend
   ```

   `run.py` refuses a second test run of the same method and version with a different config. Changing the method means bumping its version, so `test_ledger.jsonl` shows how many test runs each idea got.

5. Compare against the baseline (free):

   ```bash
   .venv/bin/python -m evals.agent_overload.compare <baseline_run_id> <candidate_run_id>
   ```

   It pairs the runs by case at each split, suite, mode and N. It reports each metric's difference (candidate − baseline) with a paired 95% bootstrap CI, and a McNemar test on each case's majority outcome, where a tie between reps counts as not correct. It writes `results/comparisons/<a>__vs__<b>/compare.md` and `compare.json`.

   It refuses to compare runs with different case sets or splits, fake-model runs, capped runs and failed runs. It warns when the model slugs, the provider, the harness version or the concurrency differ (latency is only comparable at the same concurrency, ideally on the same day). The baseline's `full` run contains the test split, so it pairs with a candidate's `test` run on the test templates.

## What a run writes

`evals/agent_overload/results/<run_id>/`, with `run_id = <UTC yyyymmdd-HHMMSS>-<method>-<config hash[:8]>`:

| File | Committed | Content |
| --- | --- | --- |
| `config.json` | yes | The input config, plus everything recorded with the run: git SHA and dirty flag, prompt and source-tree hashes, model slugs, settings, and end-of-run counts |
| `turns.jsonl.gz` | yes | One line per turn-run: label, delegations, outcomes, tags, tokens, cost, latency |
| `sequences.jsonl.gz` | yes | One line per sequence-run: agents added, the agent-to-thread map, end-of-sequence stats |
| `calls.jsonl.gz` | yes | One record per model call (usage, cost, provider, seed, latency, attempts) |
| `metrics.json` | yes | Every metric with CIs |
| `report.md` | yes | The readable report |
| `raw/` | no | Raw request and response JSON per call (ignored by git) |

Fake-model runs go to `results/_fake/` (ignored by git) unless `--results-dir` is given.

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | Done | Check the outputs as described for the step |
| 1 | Error before any spend (for example the fixtures aren't frozen, a hash doesn't match, or input is missing) | Read the message; fix the prerequisite |
| 2 | Refused: no `--confirm-spend` | Expected without the flag; add it to run for real |
| 3 | Refused: the ledger total plus the estimate × 1.25 would pass $50 | Stop and decide with the agent what to cut (design: "What to cut if measured costs come in high") |
| 4 | Refused: this method and version already has a test run with a different config | Bump the method version |
| 5 | Refused: uncommitted changes | Commit, or pass `--allow-dirty` (the report flags it) |
| 6 | Refused: a pinned model's slug changed | Stop and decide with the agent |
| 7 | Run finished but failed: api_error above 2%, or a unit crashed | Results are written but unusable for comparisons; check `config.json` (`end`) and rerun |
| 8 | Capped: the per-run cost cap was reached | Partial results are written. Generation steps: rerun to continue. `run.py`: the run is unusable; check costs, then rerun with a higher `--max-cost` if the budget allows |

## File map

| Path | What |
| --- | --- |
| `evals/agent_overload/configs/baseline_names_only.json` | The baseline run config (models, provider pin, sizes, reps, budget) |
| `evals/agent_overload/configs/pricing.json` | Prices used for estimates only |
| `evals/agent_overload/fixtures/v1/` | The case set; `review/` holds the generation and review records |
| `evals/agent_overload/generation/` | The generation scripts and `prompts/` |
| `evals/agent_overload/harness/` | State, rosters, scoring, metrics, report, model client, methods |
| `evals/agent_overload/run.py`, `compare.py` | The CLIs |
| `evals/agent_overload/results/` | Run directories, `spend_ledger.jsonl`, `test_ledger.jsonl` |
| `evals/agent_overload/tests/` | Unit and fake-model end-to-end tests |
