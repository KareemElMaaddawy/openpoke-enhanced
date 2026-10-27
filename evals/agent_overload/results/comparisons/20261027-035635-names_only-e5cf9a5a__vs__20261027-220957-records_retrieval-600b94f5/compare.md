# Comparison: records_retrieval v1 vs names_only v1

Baseline run `20261027-035635-names_only-e5cf9a5a`, candidate run `20261027-220957-records_retrieval-600b94f5`, case set `8ac0f493fdaf81d3`.
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
| dev|sequence|carried|all_N | 96 | 10.9% [0.0, 22.4] | 15.0% [10.3, 18.8] | -19.2% [-31.0, -7.3] | -62.5% [-75.0, -46.9] | 1,315 [962, 1,669] | $0.00004 [$0.00003, $0.00005] | 0.00333 (7/24) |
| dev|sequence|corrected|all_N | 96 | 1.6% [-3.6, 6.2] | 9.2% [3.3, 15.0] | -3.3% [-10.3, 0.0] | -56.2% [-78.1, -34.4] | 767 [402, 1,400] | $0.00011 [$0.00011, $0.00011] | 0.383 (8/13) |
| dev|single|-|all_N | 120 | 15.8% [7.1, 25.4] | 4.9% [1.1, 9.5] | -4.3% [-10.3, 0.0] | -71.2% [-87.5, -52.3] | 826 [374, 1,301] | $0.00013 [$0.00012, $0.00015] | 1.09e-05 (4/29) |

## Per roster size

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|10 | 48 | 7.3% [-3.1, 14.6] | 13.3% [3.4, 24.1] | -13.3% [-25.0, 0.0] | -56.2% [-87.5, -25.0] | 3,982 [3,522, 4,542] | $0.00016 [$0.00014, $0.00018] | 0.118 (4/11) |
| dev|sequence|carried|200 | 48 | 14.6% [2.1, 33.3] | 16.7% [6.9, 25.0] | -25.0% [-46.4, -13.3] | -68.8% [-87.5, -50.0] | -1,351 [-2,109, -786] | $-0.00007 [$-0.00009, $-0.00005] | 0.0213 (3/13) |
| dev|sequence|corrected|10 | 48 | 1.0% [-10.4, 10.4] | 6.7% [0.0, 13.3] | -1.7% [-5.2, 0.0] | -43.8% [-81.2, -12.5] | 3,720 [3,258, 4,183] | $0.00024 [$0.00022, $0.00025] | 0.508 (3/6) |
| dev|sequence|corrected|200 | 48 | 2.1% [-5.2, 7.3] | 11.7% [0.0, 23.3] | -5.0% [-15.5, 0.0] | -68.8% [-87.5, -50.0] | -2,185 [-3,182, -832] | $-0.00002 [$-0.00003, $-0.00000] | 0.774 (5/7) |
| dev|single|-|10 | 60 | 15.8% [5.8, 25.8] | 2.4% [0.0, 8.2] | -2.4% [-7.9, 0.0] | -69.2% [-90.9, -44.4] | 3,543 [3,176, 3,886] | $0.00020 [$0.00019, $0.00021] | 0.00342 (1/12) |
| dev|single|-|200 | 60 | 15.8% [5.0, 27.5] | 7.3% [0.0, 15.6] | -6.1% [-13.5, 0.0] | -73.1% [-90.9, -54.5] | -1,891 [-2,703, -1,013] | $0.00007 [$0.00004, $0.00010] | 0.00258 (3/17) |
