# Agent overload run 20261027-023444-names_only-8ec89b24

## 1. Run identity

|  |  |
| --- | --- |
| Run id | 20261027-023444-names_only-8ec89b24 |
| Profile | smoke |
| Method | names_only v1 |
| Case set | v1 (8ac0f493fdaf81d3) |
| Interaction model | openai/gpt-6-luna (observed slug: openai/gpt-6-luna-20260922) |
| Summarizer model | openai/gpt-6-luna |
| Provider settings | {'order': ['openai'], 'allow_fallbacks': False} |
| Providers seen | OpenAI (468) |
| Git | ed99e64209afad8232e5c321ec24a3f4ae8f8926 |
| Harness / scorer | 1.0.0 / 1 |
| Started / ended | 2026-10-27T02:34:44Z / 2026-10-27T03:00:08Z |

No warnings.

Turns run: 68, api_error: 0 (0.00%), loop limit: 52, summarizer errors: 0.

## 2. Headline (dev split, single-turn suite)

Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the routing method's calls only.

| N | Accuracy | False spawn | Misroute | False reuse | Missed deleg. | Extra deleg. | Duplicate rate | Roster tok/turn | Input tok/turn | Cost/turn | Latency p50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 50.0% [20.0, 80.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 75.0% [20.0, 100.0] | 22.2% [0.0, 50.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 824 [416, 824] | 29,614 [14,057, 29,935] | $0.00071 [$0.00056, $0.00084] | 16.16s [11.08s, 18.84s] |
| 200 | 50.0% [20.0, 80.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 100.0% [100.0, 100.0] | 11.1% [0.0, 37.5] | 0.0% [0.0, 0.0] | 20.0% [20.0, 20.0] | 17,400 [16,731, 17,408] | 46,258 [31,548, 47,080] | $0.00115 [$0.00096, $0.00132] | 19.39s [11.66s, 24.03s] |
| all N | 50.0% [25.0, 75.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 87.5% [60.0, 100.0] | 16.7% [0.0, 43.8] | 0.0% [0.0, 0.0] | n/a | 11,294 [3,674, 16,727] | 30,047 [23,296, 38,329] | $0.00093 [$0.00080, $0.00106] | 16.89s [15.57s, 20.67s] |

## 3. Accuracy drop point

- **dev:** none detected (first N whose accuracy is more than 5 points below N=10 with a paired 95% CI excluding 0).
  Differences from N=10: N=200: 0.0% [-30.0, 30.0]

## 4. Confusion matrices

**N = 10** (dev, rows = label kind, columns = primary outcome)

| label \ outcome | correct_create | correct_no_delegation | correct_reuse | false_reuse | missed_delegation |
| --- | --- | --- | --- | --- | --- |
| CREATE | 1 | 0 | 0 | 3 | 0 |
| NO_DELEGATION | 0 | 1 | 0 | 0 | 0 |
| REUSE | 0 | 0 | 3 | 0 | 1 |
| REUSE_ANY | 0 | 0 | 0 | 0 | 1 |

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
| 10 | 50.0% [0.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (3) | 100.0% [100.0, 100.0] (1) | 50.0% [0.0, 100.0] (2) |
| 200 | 100.0% [100.0, 100.0] (2) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (3) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | execution_result | user |
| --- | --- | --- | --- |
| 10 | 50.0% [0.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 33.3% [0.0, 75.0] (6) |
| 200 | 50.0% [0.0, 100.0] (2) | 100.0% [100.0, 100.0] (2) | 33.3% [0.0, 75.0] (6) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 25.0% [0.0, 80.0] (4) | 100.0% [100.0, 100.0] (1) | 75.0% [25.0, 100.0] (4) | 0.0% [0.0, 0.0] (1) |
| 200 | 0.0% [0.0, 0.0] (4) | 100.0% [100.0, 100.0] (1) | 75.0% [25.0, 100.0] (4) | 100.0% [100.0, 100.0] (1) |

**target_position** (accuracy [95% CI], n)

| N | first_third | middle_third | none |
| --- | --- | --- | --- |
| 10 | 50.0% [0.0, 100.0] (2) | 40.0% [0.0, 100.0] (5) | 66.7% [0.0, 100.0] (3) |
| 200 | 50.0% [0.0, 100.0] (2) | 60.0% [16.7, 100.0] (5) | 33.3% [0.0, 100.0] (3) |

**target_age_bucket** (accuracy [95% CI], n)

| N | none | recent |
| --- | --- | --- |
| 10 | 40.0% [0.0, 100.0] (5) | 60.0% [14.3, 100.0] (5) |
| 200 | 20.0% [0.0, 66.7] (5) | 80.0% [37.5, 100.0] (5) |

**name_descriptiveness** (accuracy [95% CI], n)

| N | none | partial | specific |
| --- | --- | --- | --- |
| 10 | 40.0% [0.0, 100.0] (5) | 100.0% [100.0, 100.0] (1) | 50.0% [0.0, 100.0] (4) |
| 200 | 20.0% [0.0, 66.7] (5) | 100.0% [100.0, 100.0] (1) | 75.0% [25.0, 100.0] (4) |

**history_type** (accuracy [95% CI], n)

| N | short | summarized |
| --- | --- | --- |
| 10 | 55.6% [22.2, 88.9] (9) | 0.0% [0.0, 0.0] (1) |
| 200 | 44.4% [12.5, 77.8] (9) | 100.0% [100.0, 100.0] (1) |

**target_name_visible** (accuracy [95% CI], n)

| N | True | none |
| --- | --- | --- |
| 10 | 60.0% [14.3, 100.0] (5) | 40.0% [0.0, 100.0] (5) |
| 200 | 80.0% [37.5, 100.0] (5) | 20.0% [0.0, 66.7] (5) |

## 6. Sequences

### dev

| N | accuracy (carried) | accuracy (corrected) | carried − corrected | recency lock (corrected) |
| --- | --- | --- | --- | --- |
| 10 | 83.3% [83.3, 83.3] | 83.3% [83.3, 83.3] | 0.0% [0.0, 0.0] | 14.3% [14.3, 14.3] |
| 200 | 58.3% [58.3, 58.3] | 83.3% [83.3, 83.3] | -25.0% [-25.0, -25.0] | 0.0% [0.0, 0.0] |

Compounding: accuracy carried forward minus corrected each turn, by turn index.

| N | t1 | t2 | t3 | t4 | t5 | t6 | t7 | t8 | t9 | t10 | t11 | t12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 0.0% | 0.0% | -100.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 200 | 0.0% | 0.0% | -100.0% | 0.0% | -100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | -100.0% | 0.0% |

Duplicates (carried forward, end of sequence).

| N | runs | duplicate rate | inflation ratio | extra agents / thread | created − gold | slug collisions |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 1 | 0.0% [0.0, 0.0] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | -1.00 [-1.00, -1.00] | 0 |
| 200 | 1 | 20.0% [20.0, 20.0] | 1.25 [1.25, 1.25] | 0.17 [0.17, 0.17] | -1.00 [-1.00, -1.00] | 0 |

**query_style** (accuracy [95% CI], n)

| N | any | explicit | implicit_follow_up | near_distractor | paraphrased | plain |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (3) | 100.0% [100.0, 100.0] (3) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (2) | 50.0% [50.0, 50.0] (2) |
| 200 | 100.0% [100.0, 100.0] (3) | 66.7% [66.7, 66.7] (3) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 50.0% [50.0, 50.0] (2) | 0.0% [0.0, 0.0] (2) |

**message_subtype** (accuracy [95% CI], n)

| N | email_alert | user |
| --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 81.8% [81.8, 81.8] (11) |
| 200 | 100.0% [100.0, 100.0] (1) | 54.5% [54.5, 54.5] (11) |

**label_kind** (accuracy [95% CI], n)

| N | CREATE | NO_DELEGATION | REUSE | REUSE_ANY |
| --- | --- | --- | --- | --- |
| 10 | 50.0% [50.0, 50.0] (2) | 100.0% [100.0, 100.0] (2) | 85.7% [85.7, 85.7] (7) | 100.0% [100.0, 100.0] (1) |
| 200 | 0.0% [0.0, 0.0] (2) | 100.0% [100.0, 100.0] (2) | 57.1% [57.1, 57.1] (7) | 100.0% [100.0, 100.0] (1) |

**turn_index** (accuracy [95% CI], n)

| N | 1 | 10 | 11 | 12 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) |
| 200 | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 0.0% [0.0, 0.0] (1) | 100.0% [100.0, 100.0] (1) | 100.0% [100.0, 100.0] (1) |

## 7. Tokens

**dev:** roster tokens per call ≈ 10.90 × N + 312.36 (least squares over 20 turn-runs).

| N | roster tok/call | roster tok/turn | input tok/turn p50 | input tok/turn p95 | routing calls/turn |
| --- | --- | --- | --- | --- | --- |
| 10 | 104 [103, 105] | 824 [416, 824] | 29,614 [14,057, 29,935] | 30,405 | 6.20 [4.70, 7.60] |
| 200 | 2,175 [2,174, 2,176] | 17,400 [16,731, 17,408] | 46,258 [31,548, 47,080] | 53,016 | 7.00 [5.50, 8.00] |

## 8. Consistency, invalid calls, loop limits

| split | N | consistency | invalid call rate | loop limit turns | api_error turns |
| --- | --- | --- | --- | --- | --- |
| dev | 10 | n/a | 0.0% [0.0, 0.0] | 6 | 0 |
| dev | 200 | n/a | 0.0% [0.0, 0.0] | 8 | 0 |

## 9. Dev split

The headline above is the dev split (no test split in this run).

## 10. Costs

Total: $0.0813 over 468 calls.

| purpose | calls | cost | prompt tokens | completion tokens | reasoning tokens |
| --- | --- | --- | --- | --- | --- |
| routing | 454 | $0.0742 | 2,765,287 | 32,870 | 14,030 |
| summarizer | 4 | $0.0056 | 10,954 | 9,020 | 7,145 |
| token_probe | 10 | $0.0015 | 29,908 | 144 | 128 |

Price check: actual cost / cost at the pricing table's standard rates = 0.269 over 468 calls. Near 1.0 means the standard endpoint; well below or above suggests the flex or fast endpoint.

Measured per-unit costs (used by later pre-run estimates): single_turn_usd = $0.00093, sequence_turn_usd = $0.00116, summarizer_per_sequence_run_usd = $0.00139, token_probe_usd = $0.00015, routing_calls_per_turn = 6.68
