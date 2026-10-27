# Comparison: records_retrieval v1 vs names_only v1

Baseline run `20261027-035635-names_only-e5cf9a5a`, candidate run `20261027-213728-records_retrieval-ca5a5cd5`, case set `8ac0f493fdaf81d3`.
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
| dev|sequence|carried|all_N | 96 | 16.1% [7.3, 26.6] | 3.3% [0.0, 6.2] | -19.2% [-31.0, -7.3] | -62.5% [-75.0, -46.9] | 40,368 [38,410, 41,997] | $0.00171 [$0.00165, $0.00178] | 0.000113 (5/27) |
| dev|sequence|corrected|all_N | 96 | 8.9% [4.7, 12.5] | 4.2% [0.0, 8.9] | -3.3% [-10.3, 0.0] | -62.5% [-81.2, -37.5] | 36,607 [35,991, 37,107] | $0.00175 [$0.00170, $0.00181] | 0.0118 (4/16) |
| dev|single|-|all_N | 120 | 13.3% [5.4, 21.3] | 2.4% [0.0, 6.4] | -3.0% [-9.5, 2.3] | -55.8% [-72.5, -37.5] | 39,814 [38,158, 41,407] | $0.00163 [$0.00150, $0.00174] | 2.74e-05 (3/25) |

## Per roster size

| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev|sequence|carried|10 | 48 | 11.5% [4.2, 16.7] | 3.3% [0.0, 9.4] | -13.3% [-25.0, 0.0] | -56.2% [-87.5, -25.0] | 4,936 [4,570, 5,261] | $0.00021 [$0.00020, $0.00022] | 0.0352 (3/12) |
| dev|sequence|carried|200 | 48 | 20.8% [8.3, 39.6] | 3.3% [0.0, 9.7] | -25.0% [-46.4, -13.3] | -68.8% [-87.5, -50.0] | 75,800 [71,553, 79,196] | $0.00322 [$0.00311, $0.00334] | 0.00235 (2/15) |
| dev|sequence|corrected|10 | 48 | -1.0% [-8.3, 6.2] | 10.0% [0.0, 21.4] | -1.7% [-5.2, 0.0] | -43.8% [-81.2, -12.5] | 4,062 [3,328, 4,914] | $0.00024 [$0.00022, $0.00026] | 0.754 (4/6) |
| dev|sequence|corrected|200 | 48 | 18.8% [12.5, 28.1] | -1.7% [-5.2, 0.0] | -5.0% [-15.5, 0.0] | -81.2% [-100.0, -62.5] | 69,153 [68,550, 69,660] | $0.00326 [$0.00316, $0.00337] | 0.00195 (0/10) |
| dev|single|-|10 | 60 | 7.5% [-2.5, 17.5] | 2.4% [0.0, 8.3] | -2.4% [-7.9, 0.0] | -53.8% [-80.0, -26.9] | 3,973 [3,431, 4,435] | $0.00020 [$0.00018, $0.00021] | 0.146 (3/9) |
| dev|single|-|200 | 60 | 19.2% [10.0, 29.2] | 2.4% [0.0, 8.3] | -3.7% [-12.5, 4.8] | -57.7% [-77.8, -35.0] | 75,655 [72,409, 78,797] | $0.00306 [$0.00281, $0.00328] | 3.05e-05 (0/16) |
