# Comparison: records_retrieval v1 vs names_only v1

Baseline run `20261027-035635-names_only-e5cf9a5a`, candidate run `20261027-215608-records_retrieval-cdeb31cc`, case set `8ac0f493fdaf81d3`.
Differences are candidate − baseline with paired 95% bootstrap CIs over templates. McNemar uses each template's majority outcome (a tie counts as not correct).

**Warnings:**

- comparing the shared split(s) only: ['dev']
- harness version differs: 1.0.0 vs 1.1.0
- plan single_sizes differs; only shared templates and sizes are compared
- plan sequence_sizes differs; only shared templates and sizes are compared
- plan single_reps differs; only shared templates and sizes are compared
- plan sequence_reps differs; only shared templates and sizes are compared

## Pooled over N

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|all_N | 96 | 8.9% [-3.1, 19.3] | 11.7% [8.6, 13.8] | -20.8% [-31.0, -12.1] | -62.5% [-75.0, -46.9] | 67 [-676, 800] | $-0.00002 [$-0.00003, $-0.00001] | 0.0201 (11/26) |
| dev|sequence|corrected|all_N | 96 | 7.8% [-1.6, 12.5] | 7.5% [3.1, 11.7] | -3.3% [-10.3, 0.0] | -62.5% [-81.2, -37.5] | -904 [-1,166, -567] | $0.00004 [$0.00002, $0.00006] | 0.0266 (5/16) |
| dev|single|-|all_N | 120 | 10.0% [-1.2, 20.8] | 11.0% [2.5, 21.2] | -3.0% [-9.8, 2.4] | -67.3% [-83.3, -50.0] | -559 [-913, -229] | $0.00007 [$0.00006, $0.00008] | 0.00393 (9/27) |

## Per roster size

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|10 | 48 | 7.3% [-4.2, 16.7] | 10.0% [3.2, 14.3] | -16.7% [-25.0, -9.4] | -56.2% [-87.5, -25.0] | 2,681 [1,828, 3,533] | $0.00012 [$0.00010, $0.00014] | 0.118 (4/11) |
| dev|sequence|carried|200 | 48 | 10.4% [-4.2, 31.2] | 13.3% [3.6, 21.9] | -25.0% [-46.4, -13.3] | -68.8% [-87.5, -50.0] | -2,547 [-3,124, -1,999] | $-0.00016 [$-0.00017, $-0.00014] | 0.134 (7/15) |
| dev|sequence|corrected|10 | 48 | 7.3% [-4.2, 21.9] | 6.7% [0.0, 13.3] | -1.7% [-5.2, 0.0] | -43.8% [-81.2, -12.5] | 1,559 [1,303, 2,026] | $0.00012 [$0.00010, $0.00015] | 0.109 (2/8) |
| dev|sequence|corrected|200 | 48 | 8.3% [-4.2, 20.8] | 8.3% [3.1, 13.3] | -5.0% [-15.5, 0.0] | -81.2% [-100.0, -62.5] | -3,367 [-4,357, -2,437] | $-0.00004 [$-0.00006, $-0.00003] | 0.227 (3/8) |
| dev|single|-|10 | 60 | 5.8% [-6.7, 17.5] | 9.8% [2.2, 20.0] | -2.4% [-7.9, 0.0] | -61.5% [-85.7, -35.7] | 2,497 [2,067, 2,935] | $0.00015 [$0.00014, $0.00017] | 0.302 (5/10) |
| dev|single|-|200 | 60 | 14.2% [0.8, 26.7] | 12.2% [2.6, 22.9] | -3.7% [-12.5, 5.0] | -73.1% [-90.9, -54.5] | -3,616 [-4,076, -3,188] | $-0.00001 [$-0.00003, $0.00000] | 0.0072 (4/17) |
