# Agent overload run 20261027-211114-records_retrieval-5bdc0131

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-211114-records_retrieval-5bdc0131 |
| Profile | smoke |
| Method | records_retrieval v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (199) |
| Models returned | gpt-6-luna (199) |
| Git | f2cdc84402d4b99a9bce18918fa38c09f450623c |
| Harness / scorer | 1.1.0 / 1 |
| Started / ended | 2026-10-27T21:11:14Z / 2026-10-27T21:13:45Z |

No warnings.

Turns run: 68, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 25.0% [25.0, 25.0] | 4,341 [2,928, 4,392] | 14,770 [9,913, 14,990] | $0.00054 [$0.00047, $0.00062] | 5.88s [5.21s, 6.20s] |
| 200 | 90.0% [70.0, 100.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 10.0% [0.0, 30.0] | 0.0% [0.0, 0.0] | 88,148 [88,104, 93,111] | 98,654 [98,508, 98,838] | $0.00410 [$0.00393, $0.00425] | 7.15s [6.51s, 8.12s] |
| all N | 95.0% [85.0, 100.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 5.0% [0.0, 15.0] | n/a | 36,542 [31,568, 51,231] | 42,176 [40,250, 58,677] | $0.00232 [$0.00221, $0.00241] | 6.31s [6.09s, 7.19s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: -10.0% [-30.0, 0.0]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse |
| --- | --- | --- | --- |
| CREATE | 4 | 0 | 0 |
| NO_DELEGATION | 0 | 1 | 0 |
| REUSE | 0 | 0 | 4 |
| REUSE_ANY | 0 | 0 | 1 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse |
| --- | --- | --- | --- |
| CREATE | 4 | 0 | 0 |
| NO_DELEGATION | 0 | 1 | 0 |
| REUSE | 0 | 0 | 4 |
| REUSE_ANY | 0 | 0 | 1 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (2) |
| 200 | 50.0% [0.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (6) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 83.3% [50.0, 100.0] (6) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) |
| 200 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (4) | 0.0% [0.0, 0.0] (1) |

**target_position** (accuracy [95% CI], n)

| N | first_third | middle_third | none |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (5) | 100.0% [100.0, 100.0] (3) |
| 200 | 100.0% [100.0, 100.0] (2) | 80.0% [33.3, 100.0] (5) | 100.0% [100.0, 100.0] (3) |

**target_age_bucket** (accuracy [95% CI], n)

| N | none | recent |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (5) | 100.0% [100.0, 100.0] (5) |
| 200 | 100.0% [100.0, 100.0] (5) | 80.0% [33.3, 100.0] (5) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | none | partial | specific |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (5) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (5) | 100.0% [100.0, 100.0] (1) | 75.0% [25.0, 100.0] (4) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (1) |
| 200 | 100.0% [100.0, 100.0] (9) | 0.0% [0.0, 0.0] (1) |

**target_name_visible** (accuracy [95% CI], n)

| N | True | none |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (5) | 100.0% [100.0, 100.0] (5) |
| 200 | 80.0% [33.3, 100.0] (5) | 100.0% [100.0, 100.0] (5) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 83.3% [83.3, 83.3] | 100.0% [100.0, 100.0] | -16.7% [-16.7, -16.7] | 0.0% [0.0, 0.0] |
| 200 | 83.3% [83.3, 83.3] | 91.7% [91.7, 91.7] | -8.3% [-8.3, -8.3] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | -100.0% | -100.0% | 0.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | -100.0% | 0.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 1 | 25.0% [25.0, 25.0] | 1.33 [1.33, 1.33] | 0.33 [0.33, 0.33] | 2.00 [2.00, 2.00] | 0 |
| 200 | 1 | 0.0% [0.0, 0.0] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | -1.00 [-1.00, -1.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 66.7% [66.7, 66.7] (3) | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 50.0% [50.0, 50.0] (2) | 100.0% [100.0, 100.0] (2) |
| 200 | 100.0% [100.0, 100.0] (3) | 66.7% [66.7, 66.7] (3) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (2) | 50.0% [50.0, 50.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 81.8% [81.8, 81.8] (11) |
| 200 | 100.0% [100.0, 100.0] (1) | 81.8% [81.8, 81.8] (11) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 85.7% [85.7, 85.7] (7) | 0.0% [0.0, 0.0] (1) |
| 200 | 50.0% [50.0, 50.0] (2) | 100.0% [100.0, 100.0] (2) | 85.7% [85.7, 85.7] (7) | 100.0% [100.0, 100.0] (1) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) |

## 7. Tokens

**dev:** roster tokens per call ≈ 146.95 × N + 318.82 (least squares over 20 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 1,460 [1,446, 1,468] | 4,341 [2,928, 4,392] | 14,770 [9,913, 14,990] | 17,173 | 2.70 [2.40, 2.90] |
| 200 | 29,378 [29,368, 29,390] | 88,148 [88,104, 93,111] | 98,654 [98,508, 98,838] | 118,775 | 3.00 [2.70, 3.30] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.1650 over 199 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| routing | 185 | $0.1585 | 3,798,772 | 15,442 | 4,917 |
| summarizer | 4 | $0.0054 | 11,001 | 9,075 | 6,446 |
| token_probe | 10 | $0.0011 | 31,357 | 144 | 128 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00232, sequence_turn_usd = $0.00234, summarizer_per_sequence_run_usd = $0.00135, token_probe_usd = $0.00011, routing_calls_per_turn = 2.72
