# Agent overload run 20261027-215608-records_retrieval-cdeb31cc

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-215608-records_retrieval-cdeb31cc |
| Profile | dev-quick |
| Method | records_retrieval v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (1231) |
| Models returned | gpt-6-luna (919), text-embedding-3-small (312) |
| Git | 4f706c3f40784a57f0ef278417077419216acbaf |
| Harness / scorer | 1.1.0 / 1 |
| Started / ended | 2026-10-27T21:56:08Z / 2026-10-27T21:59:40Z |

No warnings.

Turns run: 312, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 88.3% [80.0, 96.7] | 9.8% [2.2, 20.0] | 0.0% [0.0, 0.0] | 7.7% [0.0, 27.3] | 1.9% [0.0, 5.8] | 1.7% [0.0, 5.0] | 14.9% [4.2, 25.0] | 2,181 [2,163, 2,211] | 12,594 [12,463, 12,871] | $0.00046 [$0.00044, $0.00048] | 6.80s [6.11s, 7.25s] |
| 200 | 86.7% [78.3, 95.0] | 12.2% [2.6, 22.9] | 2.4% [0.0, 8.3] | 0.0% [0.0, 0.0] | 1.9% [0.0, 5.8] | 1.7% [0.0, 5.0] | 20.8% [16.7, 25.0] | 2,192 [2,172, 2,214] | 12,586 [12,450, 12,742] | $0.00045 [$0.00043, $0.00047] | 6.27s [5.75s, 6.87s] |
| all N | 87.5% [79.2, 95.0] | 11.0% [2.5, 21.2] | 1.2% [0.0, 4.2] | 3.8% [0.0, 13.6] | 1.9% [0.0, 5.8] | 1.7% [0.0, 4.2] | n/a | 2,186 [2,173, 2,210] | 12,590 [12,463, 12,770] | $0.00045 [$0.00043, $0.00048] | 6.38s [6.02s, 7.11s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: -1.7% [-8.3, 5.0]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_reuse | false_spawn | missed_delegation |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 12 | 0 | 0 | 1 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 33 | 0 | 2 | 1 |
| REUSE_ANY | 0 | 0 | 3 | 0 | 2 | 0 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_spawn | misroute | missed_delegation |
| --- | --- | --- | --- | --- | --- | --- |
| CREATE | 13 | 0 | 0 | 0 | 0 | 0 |
| NO_DELEGATION | 0 | 6 | 0 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 31 | 3 | 1 | 1 |
| REUSE_ANY | 0 | 0 | 3 | 2 | 0 | 0 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 81.8% [55.6, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 77.8% [50.0, 100.0] (9) | 86.7% [66.7, 100.0] (15) | 88.9% [62.5, 100.0] (9) | 100.0% [100.0, 100.0] (7) |
| 200 | 81.8% [55.6, 100.0] (11) | 100.0% [100.0, 100.0] (9) | 66.7% [33.3, 100.0] (9) | 80.0% [58.3, 100.0] (15) | 100.0% [100.0, 100.0] (9) | 100.0% [100.0, 100.0] (7) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 75.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 88.5% [78.8, 96.3] (52) |
| 200 | 75.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 86.5% [76.6, 94.5] (52) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 92.3% [72.7, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 88.9% [77.8, 97.4] (36) | 60.0% [0.0, 100.0] (5) |
| 200 | 100.0% [100.0, 100.0] (13) | 100.0% [100.0, 100.0] (6) | 83.3% [71.1, 94.6] (36) | 60.0% [0.0, 100.0] (5) |

**target_position** (accuracy [95% CI], n)

| N | first_third | last_third | middle_third | none |
| --- | --- | --- | --- | --- |
| 10 | 86.7% [66.7, 100.0] (15) | 81.2% [60.0, 100.0] (16) | 87.5% [70.0, 100.0] (16) | 100.0% [100.0, 100.0] (13) |
| 200 | 86.7% [66.7, 100.0] (15) | 81.2% [60.0, 100.0] (16) | 81.2% [60.0, 100.0] (16) | 100.0% [100.0, 100.0] (13) |

**target_age_bucket** (accuracy [95% CI], n)

| N | mid | none | old | recent |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 94.7% [81.2, 100.0] (19) | 100.0% [100.0, 100.0] (6) | 81.8% [68.3, 94.3] (33) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (19) | 83.3% [50.0, 100.0] (6) | 78.8% [64.1, 91.7] (33) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | generic | none | partial | specific |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 94.7% [81.2, 100.0] (19) | 83.3% [57.1, 100.0] (12) | 85.7% [72.0, 96.8] (28) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (19) | 75.0% [46.2, 100.0] (12) | 82.1% [67.9, 95.7] (28) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 88.1% [77.8, 97.6] (42) | 88.9% [72.2, 100.0] (18) |
| 200 | 88.1% [77.5, 97.4] (42) | 83.3% [64.3, 100.0] (18) |

**target_name_visible** (accuracy [95% CI], n)

| N | False | True | none |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 81.8% [68.3, 94.3] (33) | 94.7% [81.2, 100.0] (19) |
| 200 | 87.5% [57.1, 100.0] (8) | 78.8% [64.1, 91.7] (33) | 100.0% [100.0, 100.0] (19) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 85.4% [72.9, 95.8] | 95.8% [91.7, 100.0] | -10.4% [-25.0, 0.0] | 0.0% [0.0, 0.0] |
| 200 | 79.2% [75.0, 87.5] | 87.5% [79.2, 95.8] | -8.3% [-18.8, 0.0] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | 0.0% | -25.0% | -25.0% | 0.0% | 0.0% | 0.0% | -25.0% | -25.0% | 0.0% | -25.0% |
| 200 | 0.0% | 0.0% | 0.0% | 0.0% | -25.0% | 0.0% | 0.0% | -25.0% | -25.0% | -25.0% | 0.0% | 0.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 4 | 14.9% [4.2, 25.0] | 1.19 [1.05, 1.34] | 0.19 [0.05, 0.34] | 1.00 [0.25, 1.75] | 0 |
| 200 | 4 | 20.8% [16.7, 25.0] | 1.27 [1.20, 1.33] | 0.27 [0.20, 0.33] | 1.50 [1.00, 2.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 78.6% [60.0, 100.0] (14) | 75.0% [46.2, 100.0] (12) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (6) | 100.0% [100.0, 100.0] (8) |
| 200 | 71.4% [66.7, 75.0] (14) | 75.0% [46.2, 100.0] (12) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 66.7% [14.3, 100.0] (6) | 100.0% [100.0, 100.0] (8) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 83.3% [57.1, 100.0] (6) | 85.7% [68.3, 97.7] (42) |
| 200 | 83.3% [57.1, 100.0] (6) | 78.6% [71.4, 86.4] (42) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (8) | 90.0% [72.7, 100.0] (10) | 84.6% [69.2, 100.0] (26) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (8) | 100.0% [100.0, 100.0] (10) | 76.9% [68.0, 92.0] (26) | 0.0% [0.0, 0.0] (4) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) |
| 200 | 100.0% [100.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 75.0% [25.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (4) | 50.0% [0.0, 100.0] (4) | 25.0% [0.0, 75.0] (4) |

## 7. Tokens

**dev:** roster tokens per call ≈ 0.03 × N + 1121.37 (least squares over 120 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 734 [727, 742] | 2,181 [2,163, 2,211] | 12,594 [12,463, 12,871] | 16,807 | 2.85 [2.75, 2.95] |
| 200 | 737 [729, 745] | 2,192 [2,172, 2,214] | 12,586 [12,450, 12,742] | 16,412 | 2.77 [2.65, 2.87] |

### Retrieval (single-turn suite)

Recall@k: share of reuse turns whose target agent is in the method's first k candidates (turns where retrieval ran). Target excluded: share of delegating turns that went wrong because the target agent was hidden.

| split | N | agents shown | recall@1 | recall@3 | recall@5 | recall@8 | recall@10 | recall@20 | target excluded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 10 | 5 [5, 5] | 43.9% [29.8, 59.5] | 97.6% [92.1, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] |
| dev | 200 | 5 [5, 5] | 43.9% [29.8, 59.5] | 95.1% [87.8, 100.0] | 97.6% [91.7, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 1.9% [0.0, 5.9] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 1.7% [0.0, 5.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.1958 over 1231 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| embed_query | 312 | $0.0005 | 26,657 | 0 | 0 |
| routing | 843 | $0.1724 | 4,578,061 | 73,161 | 26,166 |
| summarizer | 16 | $0.0200 | 44,543 | 35,060 | 25,455 |
| token_probe | 60 | $0.0028 | 192,073 | 848 | 656 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00045, sequence_turn_usd = $0.00062, summarizer_per_sequence_run_usd = $0.00125, token_probe_usd = $0.00005, routing_calls_per_turn = 2.70
