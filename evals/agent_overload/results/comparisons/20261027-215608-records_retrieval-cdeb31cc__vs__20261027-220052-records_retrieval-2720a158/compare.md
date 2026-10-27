# Comparison: records_retrieval v1 vs records_retrieval v1

Baseline run `20261027-215608-records_retrieval-cdeb31cc`, candidate run `20261027-220052-records_retrieval-2720a158`, case set `8ac0f493fdaf81d3`.
Differences are candidate − baseline with paired 95% bootstrap CIs over templates. McNemar uses each template's majority outcome (a tie counts as not correct).

## Pooled over N

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|all_N | 96 | 4.2% [-6.2, 14.6] | 3.3% [-6.7, 17.2] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | -571 [-1,000, -177] | $-0.00001 [$-0.00002, $0.00001] | 0.388 (4/8) |
| dev|sequence|corrected|all_N | 96 | 0.0% [0.0, 0.0] | 1.7% [0.0, 5.2] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | -490 [-668, -303] | $-0.00003 [$-0.00004, $-0.00001] | 1 (2/2) |
| dev|single|-|all_N | 120 | 0.0% [-4.2, 4.2] | -3.7% [-9.2, 1.4] | 0.0% [-3.7, 3.7] | 3.8% [0.0, 12.5] | -609 [-879, -328] | $-0.00001 [$-0.00002, $-0.00000] | 1 (5/5) |

## Per roster size

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|10 | 48 | 2.1% [-10.4, 8.3] | 0.0% [-14.3, 16.1] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | -351 [-1,113, 701] | $-0.00002 [$-0.00006, $0.00000] | 1 (2/3) |
| dev|sequence|carried|200 | 48 | 6.2% [-8.3, 20.8] | 6.7% [-6.7, 20.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | -792 [-1,246, -338] | $0.00001 [$-0.00000, $0.00002] | 0.453 (2/5) |
| dev|sequence|corrected|10 | 48 | -2.1% [-6.2, 0.0] | 3.3% [0.0, 10.3] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 7 [-294, 175] | $-0.00000 [$-0.00003, $0.00003] | 1 (1/0) |
| dev|sequence|corrected|200 | 48 | 2.1% [0.0, 6.2] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | 0.0% [0.0, 0.0] | -987 [-1,418, -645] | $-0.00005 [$-0.00006, $-0.00004] | 1 (1/2) |
| dev|single|-|10 | 60 | 3.3% [-5.0, 11.7] | -7.3% [-16.2, 0.0] | 0.0% [0.0, 0.0] | 7.7% [0.0, 25.0] | -726 [-1,203, -251] | $-0.00002 [$-0.00004, $-0.00001] | 0.688 (2/4) |
| dev|single|-|200 | 60 | -3.3% [-10.0, 3.3] | 0.0% [-7.3, 7.3] | 0.0% [-7.3, 7.3] | 0.0% [0.0, 0.0] | -491 [-900, -102] | $-0.00001 [$-0.00002, $0.00001] | 0.625 (3/1) |
