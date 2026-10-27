# Agent overload run 20261027-220957-records_retrieval-600b94f5

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-220957-records_retrieval-600b94f5 |
| Profile | dev-quick |
| Method | records_retrieval v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (1240) |
| Models returned | gpt-6-luna (928), text-embedding-3-small (312) |
| Git | 3fd97fffce0a1fbe95759086f03e00c2d208f3ff |
| Harness / scorer | 1.1.0 / 1 |
| Started / ended | 2026-10-27T22:09:57Z / 2026-10-27T22:13:30Z |

No warnings.

Turns run: 312, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 98.3% [95.0, 100.0] | 2.4% [0.0, 8.2] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 14.3% [3.6, 25.0] | 3,490 [3,470, 3,513] | 13,922 [13,767, 14,102] | $0.00051 [$0.00048, $0.00053] | 6.04s [5.83s, 6.52s] |
| 200 | 88.3% [80.0, 95.0] | 7.3% [0.0, 15.6] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 6.7% [1.7, 13.3] | 20.8% [16.7, 25.0] | 3,522 [3,492, 3,578] | 14,001 [13,841, 14,171] | $0.00053 [$0.00049, $0.00057] | 6.15s [5.90s, 6.89s] |
| all N | 93.3% [89.2, 97.5] | 4.9% [1.1, 9.5] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 3.3% [0.8, 6.7] | n/a | 3,502 [3,484, 3,532] | 13,950 [13,834, 14,140] | $0.00052 [$0.00049, $0.00055] | 6.13s [5.89s, 6.61s] |

## 3. Accuracy drop point

- **dev:** N = 200 (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: -10.0% [-20.0, -1.7]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_spawn |
| --- | --- | --- | --- | --- |
| CREATE | 13 | 0 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 |
| REUSE | 0 | 0 | 35 | 1 |
| REUSE_ANY | 0 | 0 | 5 | 0 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_spawn |
| --- | --- | --- | --- | --- |
| CREATE | 13 | 0 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 |
| REUSE | 0 | 0 | 35 | 1 |
| REUSE_ANY | 0 | 0 | 3 | 2 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 88.9% [63.6, 100.0] (9) | 100.0% [100.0, 100.0] (15) | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (7) |
| 200 | 72.7% [44.4, 100.0] (11) | 88.9% [62.5, 100.0] (9) | 88.9% [62.5, 100.0] (9) | 93.3% [77.8, 100.0] (15) | 88.9% [62.5, 100.0] (9) | 100.0% [100.0, 100.0] (7) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 98.1% [93.9, 100.0] (52) |
| 200 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 86.5% [76.8, 94.6] (52) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 97.2% [90.6, 100.0] (36) | 100.0% [100.0, 100.0] (5) |
| 200 | 100.0% [100.0, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 88.9% [77.5, 97.4] (36) | 40.0% [0.0, 100.0] (5) |

**target_position** (accuracy [95% CI], n)

| N | first_third | last_third | middle_third | none |
| --- | --- | --- | --- | --- |
| 10 | 93.3% [77.8, 100.0] (15) | 100.0% [100.0, 100.0] (16) | 100.0% [100.0, 100.0] (16) | 100.0% [100.0, 100.0] (13) |
| 200 | 93.3% [76.9, 100.0] (15) | 87.5% [69.2, 100.0] (16) | 75.0% [50.0, 94.1] (16) | 100.0% [100.0, 100.0] (13) |

**target_age_bucket** (accuracy [95% CI], n)

| N | mid | none | old | recent |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (19) | 100.0% [100.0, 100.0] (6) | 97.0% [89.7, 100.0] (33) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (19) | 66.7% [25.0, 100.0] (6) | 84.8% [72.1, 96.6] (33) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | generic | none | partial | specific |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (19) | 100.0% [100.0, 100.0] (12) | 96.4% [88.0, 100.0] (28) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (19) | 75.0% [45.5, 100.0] (12) | 85.7% [71.9, 96.8] (28) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 97.6% [92.1, 100.0] (42) | 100.0% [100.0, 100.0] (18) |
| 200 | 92.9% [84.1, 100.0] (42) | 77.8% [57.1, 94.7] (18) |

**target_name_visible** (accuracy [95% CI], n)

| N | False | True | none |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 97.0% [89.7, 100.0] (33) | 100.0% [100.0, 100.0] (19) |
| 200 | 75.0% [40.0, 100.0] (8) | 84.8% [72.1, 96.6] (33) | 100.0% [100.0, 100.0] (19) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 85.4% [77.1, 95.8] | 89.6% [83.3, 95.8] | -4.2% [-12.5, 4.2] | 0.0% [0.0, 0.0] |
| 200 | 83.3% [77.1, 89.6] | 81.2% [75.0, 87.5] | 2.1% [-8.3, 12.5] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | 0.0% | 25.0% | 0.0% | 0.0% | 0.0% | -50.0% | 0.0% | -25.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | -25.0% | 0.0% | 0.0% | 0.0% | 25.0% | -25.0% | 50.0% | -25.0% | 0.0% | 25.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 4 | 14.3% [3.6, 25.0] | 1.18 [1.04, 1.34] | 0.18 [0.04, 0.34] | 1.00 [0.25, 1.75] | 0 |
| 200 | 4 | 20.8% [16.7, 25.0] | 1.27 [1.20, 1.33] | 0.27 [0.20, 0.33] | 1.50 [1.00, 2.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 85.7% [71.4, 100.0] (14) | 83.3% [71.4, 100.0] (12) | 50.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 83.3% [57.1, 100.0] (6) | 100.0% [100.0, 100.0] (8) |
| 200 | 85.7% [75.0, 100.0] (14) | 75.0% [46.2, 100.0] (12) | 50.0% [0.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (6) | 100.0% [100.0, 100.0] (8) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 83.3% [57.1, 100.0] (6) | 85.7% [75.0, 95.5] (42) |
| 200 | 100.0% [100.0, 100.0] (6) | 81.0% [73.2, 88.4] (42) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 80.8% [69.2, 92.3] (26) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 76.9% [68.0, 92.0] (26) | 50.0% [0.0, 100.0] (4) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 25.0% [0.0, 75.0] (4) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) |

## 7. Tokens

**dev:** roster tokens per call ≈ 0.05 × N + 1444.46 (least squares over 120 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 1,167 [1,162, 1,178] | 3,490 [3,470, 3,513] | 13,922 [13,767, 14,102] | 17,674 | 2.82 [2.70, 2.92] |
| 200 | 1,178 [1,172, 1,192] | 3,522 [3,492, 3,578] | 14,001 [13,841, 14,171] | 18,252 | 2.85 [2.70, 2.98] |

### Retrieval (single-turn suite)

Recall@k: share of reuse turns whose target agent is in the method's first k candidates (turns where retrieval ran). Target excluded: share of delegating turns that went wrong because the target agent was hidden.

| split | N | agents shown | recall@1 | recall@3 | recall@5 | recall@8 | recall@10 | recall@20 | target excluded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 10 | 8 [8, 8] | 43.9% [29.8, 59.5] | 97.6% [92.1, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] |
| dev | 200 | 8 [8, 8] | 43.9% [29.8, 59.5] | 95.1% [87.8, 100.0] | 97.6% [91.7, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.2163 over 1240 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| embed_query | 312 | $0.0005 | 26,945 | 0 | 0 |
| routing | 852 | $0.1928 | 5,024,299 | 77,304 | 29,072 |
| summarizer | 16 | $0.0200 | 44,556 | 35,027 | 25,092 |
| token_probe | 60 | $0.0029 | 198,810 | 880 | 640 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00052, sequence_turn_usd = $0.00068, summarizer_per_sequence_run_usd = $0.00125, token_probe_usd = $0.00005, routing_calls_per_turn = 2.73
