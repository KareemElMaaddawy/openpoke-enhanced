# Agent overload run 20261027-034627-names_only-6ba0954b

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-034627-names_only-6ba0954b |
| Profile | smoke |
| Method | names_only v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (2) |
| Models returned | gpt-6-luna (2) |
| Git | 02da74df4f52077e192fdd5c784eb9c9c36cbb85 |
| Harness / scorer | 1.0.0 / 1 |
| Started / ended | 2026-10-27T03:46:27Z / 2026-10-27T03:46:57Z |

**Warnings:**

- FAILED: api_error rate 100.00% exceeds 2%.

Turns run: 68, api_error: 68 (100.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 200 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| all N | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: n/a

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

(no scored turns)

**N = 200** (dev, rows = label kind, columns = primary outcome)

(no scored turns)

## 5. Breakdowns

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | n/a | n/a | n/a | n/a |
| 200 | n/a | n/a | n/a | n/a |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N |
| --- |
| 10 |
| 200 |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 0 | n/a | n/a | n/a | n/a | 0 |
| 200 | 0 | n/a | n/a | n/a | n/a | 0 |

## 7. Tokens

**dev:** roster tokens per call ≈ n/a × N + n/a (least squares over 0 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | n/a | n/a | n/a | n/a | n/a |
| 200 | n/a | n/a | n/a | n/a | n/a |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | n/a | 0 | 10 |
| dev | 200 | n/a | n/a | 0 | 10 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.0027 over 2 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| summarizer | 2 | $0.0027 | 5,496 | 4,688 | 3,441 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = n/a, sequence_turn_usd = n/a, summarizer_per_sequence_run_usd = $0.00066, token_probe_usd = n/a, routing_calls_per_turn = n/a
