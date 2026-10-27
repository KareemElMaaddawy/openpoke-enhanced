# Agent overload run 20261027-213728-records_retrieval-ca5a5cd5

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-213728-records_retrieval-ca5a5cd5 |
| Profile | dev-quick |
| Method | records_retrieval v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (912) |
| Models returned | gpt-6-luna (912) |
| Git | df1b39a99fd457f33192da29709d239bdc5ef70c |
| Harness / scorer | 1.1.0 / 1 |
| Started / ended | 2026-10-27T21:37:28Z / 2026-10-27T21:49:52Z |

No warnings.

Turns run: 312, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 90.0% [81.7, 96.7] | 2.4% [0.0, 8.3] | 0.0% [0.0, 0.0] | 15.4% [0.0, 38.9] | 1.9% [0.0, 5.8] | 3.3% [0.0, 8.3] | 7.7% [0.0, 15.5] | 4,376 [4,362, 4,402] | 14,746 [14,553, 14,871] | $0.00050 [$0.00047, $0.00053] | 8.63s [7.20s, 14.56s] |
| 200 | 91.7% [85.0, 98.3] | 2.4% [0.0, 8.3] | 2.4% [0.0, 7.7] | 15.4% [0.0, 37.5] | 0.0% [0.0, 0.0] | 1.7% [0.0, 5.0] | 7.7% [0.0, 15.5] | 88,125 [88,104, 88,158] | 98,577 [98,375, 98,754] | $0.00352 [$0.00326, $0.00376] | 8.46s [7.51s, 10.28s] |
| all N | 90.8% [84.2, 96.7] | 2.4% [0.0, 6.4] | 1.2% [0.0, 3.8] | 15.4% [0.0, 35.0] | 0.9% [0.0, 2.9] | 2.5% [0.0, 6.7] | n/a | 37,752 [36,545, 37,758] | 42,812 [42,242, 42,836] | $0.00201 [$0.00187, $0.00214] | 8.50s [7.73s, 10.26s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: 1.7% [-5.0, 8.3]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_reuse | false_spawn | missed_delegation |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 11 | 0 | 0 | 2 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 36 | 0 | 0 | 0 |
| REUSE_ANY | 0 | 0 | 3 | 0 | 1 | 1 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_reuse | false_spawn | misroute |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 11 | 0 | 0 | 2 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 35 | 0 | 1 | 0 |
| REUSE_ANY | 0 | 0 | 4 | 0 | 0 | 1 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 72.7% [42.9, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (9) | 80.0% [56.2, 100.0] (15) | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (7) |
| 200 | 90.9% [70.0, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 88.9% [62.5, 100.0] (9) | 86.7% [66.7, 100.0] (15) | 100.0% [100.0, 100.0] (9) | 85.7% [50.0, 100.0] (7) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 88.5% [79.2, 96.2] (52) |
| 200 | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 90.4% [82.0, 98.0] (52) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 84.6% [61.1, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 97.2% [90.9, 100.0] (36) | 40.0% [0.0, 100.0] (5) |
| 200 | 84.6% [62.5, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 94.4% [86.1, 100.0] (36) | 80.0% [33.3, 100.0] (5) |

**target_position** (accuracy [95% CI], n)

| N | first_third | last_third | middle_third | none |
| --- | --- | --- | --- | --- |
| 10 | 93.3% [78.6, 100.0] (15) | 87.5% [66.7, 100.0] (16) | 81.2% [58.3, 100.0] (16) | 100.0% [100.0, 100.0] (13) |
| 200 | 93.3% [76.9, 100.0] (15) | 93.8% [78.9, 100.0] (16) | 87.5% [66.7, 100.0] (16) | 92.3% [75.0, 100.0] (13) |

**target_age_bucket** (accuracy [95% CI], n)

| N | mid | none | old | recent |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 89.5% [72.7, 100.0] (19) | 83.3% [50.0, 100.0] (6) | 90.9% [80.0, 100.0] (33) |
| 200 | 100.0% [100.0, 100.0] (2) | 89.5% [73.7, 100.0] (19) | 83.3% [50.0, 100.0] (6) | 93.9% [83.9, 100.0] (33) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | generic | none | partial | specific |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 89.5% [72.7, 100.0] (19) | 91.7% [71.4, 100.0] (12) | 89.3% [76.9, 100.0] (28) |
| 200 | 100.0% [100.0, 100.0] (1) | 89.5% [73.7, 100.0] (19) | 91.7% [71.4, 100.0] (12) | 92.9% [81.5, 100.0] (28) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 90.5% [80.5, 97.8] (42) | 88.9% [72.2, 100.0] (18) |
| 200 | 92.9% [84.2, 100.0] (42) | 88.9% [72.2, 100.0] (18) |

**target_name_visible** (accuracy [95% CI], n)

| N | False | True | none |
| --- | --- | --- | --- |
| 10 | 87.5% [57.1, 100.0] (8) | 90.9% [80.0, 100.0] (33) | 89.5% [72.7, 100.0] (19) |
| 200 | 87.5% [57.1, 100.0] (8) | 93.9% [83.9, 100.0] (33) | 89.5% [73.7, 100.0] (19) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 89.6% [79.2, 97.9] | 87.5% [79.2, 95.8] | 2.1% [-6.2, 12.5] | 0.0% [0.0, 0.0] |
| 200 | 89.6% [79.2, 97.9] | 97.9% [93.8, 100.0] | -8.3% [-14.6, -2.1] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | 0.0% | 0.0% | 25.0% | 0.0% | 0.0% | 25.0% | 0.0% | -25.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | 0.0% | 0.0% | -25.0% | 0.0% | 0.0% | -25.0% | 0.0% | -25.0% | -25.0% | 0.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 4 | 7.7% [0.0, 15.5] | 1.09 [1.00, 1.18] | 0.09 [0.00, 0.18] | 0.50 [0.00, 1.00] | 0 |
| 200 | 4 | 7.7% [0.0, 15.5] | 1.09 [1.00, 1.18] | 0.09 [0.00, 0.18] | 0.50 [0.00, 1.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 85.7% [71.4, 100.0] (14) | 75.0% [46.2, 100.0] (12) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (6) | 100.0% [100.0, 100.0] (8) |
| 200 | 92.9% [80.0, 100.0] (14) | 75.0% [45.5, 100.0] (12) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (6) | 100.0% [100.0, 100.0] (8) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 83.3% [57.1, 100.0] (6) | 90.5% [77.5, 100.0] (42) |
| 200 | 100.0% [100.0, 100.0] (6) | 88.1% [75.6, 97.7] (42) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 88.5% [75.0, 100.0] (26) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 84.6% [72.0, 96.0] (26) | 75.0% [25.0, 100.0] (4) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) |

## 7. Tokens

**dev:** roster tokens per call ≈ 146.95 × N + 508.32 (least squares over 120 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 1,460 [1,456, 1,474] | 4,376 [4,362, 4,402] | 14,746 [14,553, 14,871] | 19,024 | 2.75 [2.63, 2.87] |
| 200 | 29,382 [29,376, 29,393] | 88,125 [88,104, 88,158] | 98,577 [98,375, 98,754] | 102,307 | 2.77 [2.67, 2.87] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.7175 over 912 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| routing | 836 | $0.6904 | 16,919,518 | 76,107 | 27,780 |
| summarizer | 16 | $0.0205 | 44,534 | 34,064 | 24,349 |
| token_probe | 60 | $0.0065 | 184,327 | 816 | 624 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00201, sequence_turn_usd = $0.00234, summarizer_per_sequence_run_usd = $0.00128, token_probe_usd = $0.00011, routing_calls_per_turn = 2.68
