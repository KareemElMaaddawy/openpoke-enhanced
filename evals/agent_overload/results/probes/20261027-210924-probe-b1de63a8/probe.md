# Retrieval probe 20261027-210924-probe-b1de63a8

Config `evals/agent_overload/configs/v1_records_retrieval.json`, split dev, sizes [50, 100, 200], K = 8, cost $0.0002.

Params: `{"embedding": {"dimensions": 512, "model": "openai/text-embedding-3-small"}, "full_roster_max": 0, "k": 8, "max_pinned": 3, "pin_lookback": 3, "query_with_previous_user_message": true, "render_recent": 1, "rrf_k": 60, "scorer": {"name": "interaction_agent"}, "seed_purposes": "backfill", "use_lexical": true, "use_pins": true, "use_semantic": true, "w_lex": 1.0, "w_rec": 0.5, "w_sem": 1.0}`

Recall counts single-turn REUSE / REUSE_ANY cases (123 case-size units). Modes seen: ['retrieved']. Embedding failures (lexical fallback): 0.

| group | value | n | R@1 | R@3 | R@5 | R@8 | R@10 | R@12 | R@20 | pin-only share at K |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | all | 123 | 43.9% | 88.6% | 98.4% | 98.4% | 99.2% | 99.2% | 100.0% | 21.5% |
| N | 50 | 41 | 43.9% | 85.4% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 14.6% |
| N | 100 | 41 | 43.9% | 92.7% | 97.6% | 97.6% | 100.0% | 100.0% | 100.0% | 22.5% |
| N | 200 | 41 | 43.9% | 87.8% | 97.6% | 97.6% | 97.6% | 97.6% | 100.0% | 27.5% |
| query_style | any | 15 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 20.0% |
| query_style | explicit | 27 | 11.1% | 81.5% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| query_style | implicit_follow_up | 27 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 59.3% |
| query_style | near_distractor | 27 | 11.1% | 66.7% | 92.6% | 92.6% | 96.3% | 96.3% | 100.0% | 0.0% |
| query_style | paraphrased | 27 | 22.2% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 25.9% |
| message_subtype | email_alert | 6 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| message_subtype | execution_result | 3 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| message_subtype | user | 114 | 39.5% | 87.7% | 98.2% | 98.2% | 99.1% | 99.1% | 100.0% | 23.2% |
| target_name_visible | False | 24 | 0.0% | 54.2% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| target_name_visible | True | 99 | 54.5% | 97.0% | 98.0% | 98.0% | 99.0% | 99.0% | 100.0% | 26.8% |
| history_type | short | 87 | 48.3% | 93.1% | 97.7% | 97.7% | 98.9% | 98.9% | 100.0% | 22.4% |
| history_type | summarized | 36 | 33.3% | 77.8% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 19.4% |
