# Retrieval probe 20261027-210749-probe-9cce9d45

Config `evals/agent_overload/configs/v1_records_retrieval.json`, split dev, sizes [50, 100, 200], K = 8, cost $0.0002.

Params: `{"embedding": {"dimensions": 512, "model": "openai/text-embedding-3-small"}, "full_roster_max": 0, "k": 8, "max_pinned": 3, "pin_lookback": 3, "query_with_previous_user_message": true, "render_recent": 1, "rrf_k": 60, "scorer": {"name": "interaction_agent"}, "seed_purposes": "backfill", "use_lexical": true, "use_pins": false, "use_semantic": true, "w_lex": 1.0, "w_rec": 0.0, "w_sem": 1.0}`

Recall counts single-turn REUSE / REUSE_ANY cases (123 case-size units). Modes seen: ['retrieved']. Embedding failures (lexical fallback): 0.

| group | value | n | R@1 | R@3 | R@5 | R@8 | R@10 | R@12 | R@20 | pin-only share at K |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | all | 123 | 45.5% | 62.6% | 64.2% | 68.3% | 71.5% | 73.2% | 80.5% | 0.0% |
| N | 50 | 41 | 43.9% | 68.3% | 73.2% | 78.0% | 82.9% | 85.4% | 90.2% | 0.0% |
| N | 100 | 41 | 48.8% | 61.0% | 61.0% | 65.9% | 70.7% | 70.7% | 80.5% | 0.0% |
| N | 200 | 41 | 43.9% | 58.5% | 58.5% | 61.0% | 61.0% | 63.4% | 70.7% | 0.0% |
| query_style | any | 15 | 26.7% | 33.3% | 40.0% | 53.3% | 60.0% | 66.7% | 80.0% | 0.0% |
| query_style | explicit | 27 | 74.1% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| query_style | implicit_follow_up | 27 | 11.1% | 18.5% | 22.2% | 29.6% | 29.6% | 33.3% | 48.1% | 0.0% |
| query_style | near_distractor | 27 | 74.1% | 88.9% | 88.9% | 92.6% | 92.6% | 92.6% | 96.3% | 0.0% |
| query_style | paraphrased | 27 | 33.3% | 59.3% | 59.3% | 59.3% | 70.4% | 70.4% | 77.8% | 0.0% |
| message_subtype | email_alert | 6 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| message_subtype | execution_result | 3 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| message_subtype | user | 114 | 41.2% | 59.6% | 61.4% | 65.8% | 69.3% | 71.1% | 78.9% | 0.0% |
| target_name_visible | False | 24 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| target_name_visible | True | 99 | 32.3% | 53.5% | 55.6% | 60.6% | 64.6% | 66.7% | 75.8% | 0.0% |
| history_type | short | 87 | 40.2% | 62.1% | 64.4% | 69.0% | 70.1% | 72.4% | 79.3% | 0.0% |
| history_type | summarized | 36 | 58.3% | 63.9% | 63.9% | 66.7% | 75.0% | 75.0% | 83.3% | 0.0% |
