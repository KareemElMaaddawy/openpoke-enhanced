# Agent overload run 20261027-035157-names_only-6ba0954b

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-035157-names_only-6ba0954b |
| Profile | smoke |
| Method | names_only v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: gpt-6-luna) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | None |
| Providers seen | OpenAI (199) |
| Models returned | gpt-6-luna (199) |
| Git | 31092f33a80aae05da2f9cda31ae852a54dea1fc |
| Harness / scorer | 1.0.0 / 1 |
| Started / ended | 2026-10-27T03:51:57Z / 2026-10-27T03:53:37Z |

No warnings.

Turns run: 68, api_error: 0 (0.00%), loop limit: 0, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 60.0% [30.0, 90.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 309 [258, 312] | 10,234 [8,450, 10,579] | $0.00037 [$0.00031, $0.00044] | 5.34s [3.79s, 7.79s] |
| 200 | 40.0% [10.0, 70.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 11.1% [0.0, 37.5] | 10.0% [0.0, 30.0] | 0.0% [0.0, 0.0] | 6,525 [6,522, 6,528] | 16,460 [16,382, 16,912] | $0.00064 [$0.00057, $0.00072] | 5.83s [4.89s, 7.21s] |
| all N | 50.0% [25.0, 75.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 5.6% [0.0, 18.8] | 5.0% [0.0, 15.0] | n/a | 2,386 [2,332, 3,471] | 14,112 [10,687, 15,314] | $0.00051 [$0.00044, $0.00057] | 5.56s [4.86s, 7.21s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: -20.0% [-50.0, 0.0]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_no_delegation | correct_reuse | false_reuse |
| --- | --- | --- | --- |
| CREATE | 0 | 0 | 4 |
| NO_DELEGATION | 1 | 0 | 0 |
| REUSE | 0 | 4 | 0 |
| REUSE_ANY | 0 | 1 | 0 |

**N = 200** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_no_delegation | correct_reuse | false_reuse | missed_delegation |
| --- | --- | --- | --- | --- |
| CREATE | 0 | 0 | 4 | 0 |
| NO_DELEGATION | 1 | 0 | 0 | 0 |
| REUSE | 0 | 3 | 0 | 1 |
| REUSE_ANY | 0 | 1 | 0 | 0 |

## 5. Breakdowns

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 33.3% [0.0, 100.0] (3) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (2) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (3) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 33.3% [0.0, 75.0] (6) |
| 200 | 0.0% [0.0, 0.0] (2) | 100.0% [100.0, 100.0] (2) | 33.3% [0.0, 75.0] (6) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 0.0% [0.0, 0.0] (4) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) |
| 200 | 0.0% [0.0, 0.0] (4) | 100.0% [100.0, 100.0] (1) | 50.0% [0.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) |

**target_position** (accuracy [95% CI], n)

| N | first_third | middle_third | none |
| --- | --- | --- | --- |
| 10 | 50.0% [0.0, 100.0] (2) | 80.0% [39.9, 100.0] (5) | 33.3% [0.0, 100.0] (3) |
| 200 | 50.0% [0.0, 100.0] (2) | 40.0% [0.0, 100.0] (5) | 33.3% [0.0, 100.0] (3) |

**target_age_bucket** (accuracy [95% CI], n)

| N | none | recent |
| --- | --- | --- |
| 10 | 20.0% [0.0, 66.7] (5) | 100.0% [100.0, 100.0] (5) |
| 200 | 20.0% [0.0, 66.7] (5) | 60.0% [14.3, 100.0] (5) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | none | partial | specific |
| --- | --- | --- | --- |
| 10 | 20.0% [0.0, 66.7] (5) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (4) |
| 200 | 20.0% [0.0, 66.7] (5) | 100.0% [100.0, 100.0] (1) | 50.0% [0.0, 100.0] (4) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 55.6% [22.2, 88.9] (9) | 100.0% [100.0, 100.0] (1) |
| 200 | 33.3% [0.0, 66.7] (9) | 100.0% [100.0, 100.0] (1) |

**target_name_visible** (accuracy [95% CI], n)

| N | True | none |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (5) | 20.0% [0.0, 66.7] (5) |
| 200 | 60.0% [14.3, 100.0] (5) | 20.0% [0.0, 66.7] (5) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] | 91.7% [91.7, 91.7] | 8.3% [8.3, 8.3] | 14.3% [14.3, 14.3] |
| 200 | 41.7% [41.7, 41.7] | 75.0% [75.0, 75.0] | -33.3% [-33.3, -33.3] | 14.3% [14.3, 14.3] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | -100.0% | 0.0% | 0.0% | 0.0% | 0.0% | -100.0% | -100.0% | 0.0% | -100.0% | 0.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 1 | 0.0% [0.0, 0.0] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0 |
| 200 | 1 | 0.0% [0.0, 0.0] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | -2.00 [-2.00, -2.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) |
| 200 | 66.7% [66.7, 66.7] (3) | 66.7% [66.7, 66.7] (3) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (2) | 0.0% [0.0, 0.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (11) |
| 200 | 100.0% [100.0, 100.0] (1) | 36.4% [36.4, 36.4] (11) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (7) | 100.0% [100.0, 100.0] (1) |
| 200 | 0.0% [0.0, 0.0] (2) | 100.0% [100.0, 100.0] (2) | 42.9% [42.9, 42.9] (7) | 0.0% [0.0, 0.0] (1) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) |

## 7. Tokens

**dev:** roster tokens per call ≈ 10.90 × N + -5.54 (least squares over 20 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 104 [103, 104] | 309 [258, 312] | 10,234 [8,450, 10,579] | 14,125 | 2.90 [2.60, 3.20] |
| 200 | 2,175 [2,174, 2,176] | 6,525 [6,522, 6,528] | 16,460 [16,382, 16,912] | 21,753 | 3.00 [2.70, 3.30] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 0 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.0461 over 199 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| routing | 185 | $0.0396 | 1,049,506 | 14,334 | 4,653 |
| summarizer | 4 | $0.0048 | 10,994 | 7,980 | 5,723 |
| token_probe | 10 | $0.0017 | 33,087 | 160 | 144 |

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00051, sequence_turn_usd = $0.00062, summarizer_per_sequence_run_usd = $0.00121, token_probe_usd = $0.00017, routing_calls_per_turn = 2.72
