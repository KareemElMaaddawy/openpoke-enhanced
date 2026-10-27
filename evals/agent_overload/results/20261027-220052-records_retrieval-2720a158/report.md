# Agent overload run 20261027-220052-records_retrieval-2720a158

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-220052-records_retrieval-2720a158 |
| Profile | dev-quick |
| Method | records_retrieval v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (1223) |
| Models returned | gpt-6-luna (907), text-embedding-3-small (316) |
| Git | 4f706c3f40784a57f0ef278417077419216acbaf |
| Harness / scorer | 1.1.0 / 1 |
| Started / ended | 2026-10-27T22:00:52Z / 2026-10-27T22:04:23Z |

No warnings.

Turns run: 312, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 91.7% [85.0, 98.3] | 2.4% [0.0, 7.7] | 0.0% [0.0, 0.0] | 15.4% [0.0, 40.0] | 1.9% [0.0, 5.8] | 1.7% [0.0, 5.0] | 14.0% [4.2, 22.3] | 1,774 [1,761, 1,806] | 12,154 [12,011, 12,395] | $0.00044 [$0.00041, $0.00046] | 6.39s [5.71s, 6.90s] |
| 200 | 83.3% [73.3, 91.7] | 12.2% [2.7, 23.3] | 2.4% [0.0, 8.3] | 0.0% [0.0, 0.0] | 3.7% [0.0, 9.4] | 5.0% [0.0, 11.7] | 17.1% [0.0, 34.3] | 1,790 [1,758, 1,818] | 12,130 [11,984, 12,368] | $0.00044 [$0.00042, $0.00047] | 5.91s [5.50s, 6.31s] |
| all N | 87.5% [80.8, 93.3] | 7.3% [2.0, 14.3] | 1.2% [0.0, 4.2] | 7.7% [0.0, 20.0] | 2.8% [0.0, 7.5] | 3.3% [0.8, 6.7] | n/a | 1,780 [1,764, 1,815] | 12,142 [12,006, 12,360] | $0.00044 [$0.00042, $0.00046] | 6.12s [5.71s, 6.45s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: -8.3% [-18.3, 1.7]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_reuse | false_spawn | missed_delegation |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 11 | 0 | 0 | 2 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 35 | 0 | 0 | 1 |
| REUSE_ANY | 0 | 0 | 4 | 0 | 1 | 0 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_spawn | misroute | missed_delegation |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 13 | 0 | 0 | 0 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 31 | 3 | 1 | 1 |
| REUSE_ANY | 0 | 0 | 2 | 2 | 0 | 1 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 90.9% [70.0, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (9) | 80.0% [56.2, 100.0] (15) | 100.0% [100.0, 100.0] (9) | 85.7% [50.0, 100.0] (7) |
| 200 | 72.7% [42.9, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 66.7% [33.3, 100.0] (9) | 86.7% [66.7, 100.0] (15) | 77.8% [45.5, 100.0] (9) | 100.0% [100.0, 100.0] (7) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 75.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 92.3% [84.0, 98.2] (52) |
| 200 | 75.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 82.7% [72.0, 92.3] (52) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 84.6% [60.0, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 94.4% [86.5, 100.0] (36) | 80.0% [33.3, 100.0] (5) |
| 200 | 100.0% [100.0, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 80.6% [66.7, 92.7] (36) | 40.0% [0.0, 100.0] (5) |

**target_position** (accuracy [95% CI], n)

| N | first_third | last_third | middle_third | none |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (15) | 93.8% [78.9, 100.0] (16) | 81.2% [60.0, 100.0] (16) | 92.3% [75.0, 100.0] (13) |
| 200 | 73.3% [50.0, 94.1] (15) | 81.2% [59.1, 100.0] (16) | 81.2% [60.0, 100.0] (16) | 100.0% [100.0, 100.0] (13) |

**target_age_bucket** (accuracy [95% CI], n)

| N | mid | none | old | recent |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 89.5% [73.3, 100.0] (19) | 83.3% [50.0, 100.0] (6) | 93.9% [85.2, 100.0] (33) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (19) | 100.0% [100.0, 100.0] (6) | 69.7% [53.1, 84.4] (33) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | generic | none | partial | specific |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 89.5% [73.3, 100.0] (19) | 100.0% [100.0, 100.0] (12) | 89.3% [76.9, 100.0] (28) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (19) | 75.0% [46.2, 100.0] (12) | 75.0% [57.7, 90.3] (28) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 95.2% [88.1, 100.0] (42) | 83.3% [64.7, 100.0] (18) |
| 200 | 83.3% [72.1, 93.5] (42) | 83.3% [64.7, 100.0] (18) |

**target_name_visible** (accuracy [95% CI], n)

| N | False | True | none |
| --- | --- | --- | --- |
| 10 | 87.5% [57.1, 100.0] (8) | 93.9% [85.2, 100.0] (33) | 89.5% [73.3, 100.0] (19) |
| 200 | 100.0% [100.0, 100.0] (8) | 69.7% [53.1, 84.4] (33) | 100.0% [100.0, 100.0] (19) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 87.5% [79.2, 95.8] | 93.8% [91.7, 97.9] | -6.2% [-16.7, 4.2] | 0.0% [0.0, 0.0] |
| 200 | 85.4% [75.0, 95.8] | 89.6% [83.3, 95.8] | -4.2% [-20.8, 12.5] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | -25.0% | -25.0% | -25.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | 0.0% | 25.0% | -50.0% | 0.0% | 0.0% | 0.0% | -25.0% | 25.0% | 0.0% | -25.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 4 | 14.0% [4.2, 22.3] | 1.18 [1.05, 1.29] | 0.17 [0.05, 0.29] | 1.00 [0.25, 1.75] | 0 |
| 200 | 4 | 17.1% [0.0, 34.3] | 1.27 [1.00, 1.53] | 0.27 [0.00, 0.53] | 1.50 [0.00, 3.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 85.7% [71.4, 100.0] (14) | 83.3% [50.0, 100.0] (12) | 50.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (6) | 100.0% [100.0, 100.0] (8) |
| 200 | 85.7% [71.4, 100.0] (14) | 83.3% [66.7, 100.0] (12) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 50.0% [14.3, 100.0] (6) | 100.0% [100.0, 100.0] (8) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (6) | 85.7% [75.0, 95.5] (42) |
| 200 | 100.0% [100.0, 100.0] (6) | 83.3% [72.1, 95.1] (42) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 84.6% [72.0, 96.0] (26) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 80.8% [67.9, 96.3] (26) | 50.0% [0.0, 100.0] (4) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 25.0% [0.0, 75.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) |

## 7. Tokens

**dev:** roster tokens per call ≈ 0.01 × N + 1325.00 (least squares over 120 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 598 [590, 609] | 1,774 [1,761, 1,806] | 12,154 [12,011, 12,395] | 16,224 | 2.78 [2.67, 2.90] |
| 200 | 598 [590, 606] | 1,790 [1,758, 1,818] | 12,130 [11,984, 12,368] | 15,956 | 2.75 [2.63, 2.87] |

### Retrieval (single-turn suite)

Recall@k: share of reuse turns whose target agent is in the method's first k candidates (turns where retrieval ran). Target excluded: share of delegating turns that went wrong because the target agent was hidden.

| split | N | agents shown | recall@1 | recall@3 | recall@5 | recall@8 | recall@10 | recall@20 | target excluded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 10 | 5 [5, 5] | 43.9% [29.8, 59.5] | 97.6% [92.1, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] |
| dev | 200 | 5 [5, 5] | 43.9% [29.8, 59.5] | 95.1% [87.8, 100.0] | 97.6% [91.7, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 1.9% [0.0, 5.9] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.1904 over 1223 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| embed_query | 312 | $0.0005 | 25,025 | 0 | 0 |
| embed_records | 4 | $0.0004 | 20,332 | 0 | 0 |
| routing | 831 | $0.1673 | 4,404,795 | 74,015 | 27,502 |
| summarizer | 16 | $0.0197 | 44,520 | 34,346 | 24,426 |
| token_probe | 60 | $0.0025 | 171,514 | 752 | 640 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00044, sequence_turn_usd = $0.00060, summarizer_per_sequence_run_usd = $0.00123, token_probe_usd = $0.00004, routing_calls_per_turn = 2.66
