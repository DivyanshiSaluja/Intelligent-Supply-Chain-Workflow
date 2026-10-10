# SupplyGen benchmark summary (30 runs x 4 scenarios)

## Table A. Overall comparison (mean ± SD over all scenario-runs)

| Controller | SBS | Burden % | Fill rate % | Critical availability % | Critical protection % | SBS reduction vs static % | Total cost vs static % | Cost per unit sold vs static % | Inventory vs static % |
|---|---|---|---|---|---|---|---|---|---|
| Static ROP | 10074 ± 3346 | 5.18 ± 1.61 | 94.94 ± 1.50 | 62.0 ± 16.8 | 1.0 ± 5.4 | 0.0 ± 0.0 | +0.0 | +0.0 | +0.0 |
| Adaptive ROP | 11224 ± 2787 | 5.81 ± 1.48 | 94.31 ± 1.24 | 61.6 ± 18.7 | 1.5 ± 6.1 | -16.2 ± 20.4 | -1.4 | -0.8 | -1.2 |
| Reactive dual-source | 6995 ± 3727 | 3.55 ± 1.68 | 96.47 ± 1.79 | 77.5 ± 9.1 | 4.6 ± 13.3 | 29.5 ± 26.2 | +2.3 | +0.7 | +7.3 |
| SupplyGen | 1318 ± 519 | 0.69 ± 0.28 | 99.33 ± 0.28 | 99.8 ± 0.7 | 95.0 ± 16.1 | 85.4 ± 7.2 | +6.0 | +1.2 | +19.9 |

SupplyGen SBS reduction 95% bootstrap CI: [84.0, 86.6]; lower SBS than static in 120/120 paired scenario-runs. Against the reactive dual-source baseline: 76.1 ± 14.0% lower SBS, better in 120/120.

## Table B. Per scenario

| Scenario | Static SBS | Adaptive SBS | Reactive SBS | SupplyGen SBS | Reduction % | Crit. avail. static % | Crit. avail. SupplyGen % | Invocation rate % | HITL escalations / run |
|---|---|---|---|---|---|---|---|---|---|
| A: Commodity shortage | 8144 ± 1388 | 10226 ± 1449 | 4601 ± 1099 | 1198 ± 355 | 85.1 ± 3.9 | 63.4 ± 6.0 | 100.0 ± 0.1 | 1.03 ± 0.14 | 27.6 ± 7.1 |
| B: Supplier failure | 13020 ± 1454 | 15099 ± 1300 | 5085 ± 890 | 1593 ± 699 | 87.8 ± 5.0 | 38.5 ± 6.2 | 99.5 ± 1.1 | 1.29 ± 0.14 | 14.7 ± 2.9 |
| C: Weather disruption | 6408 ± 769 | 8422 ± 895 | 5570 ± 1387 | 1494 ± 308 | 76.5 ± 5.1 | 64.7 ± 10.0 | 99.7 ± 0.8 | 0.84 ± 0.14 | 6.4 ± 1.7 |
| D: Festival surge | 12724 ± 2706 | 11150 ± 1610 | 12724 ± 2706 | 985 ± 395 | 92.1 ± 3.3 | 81.4 ± 2.6 | 100.0 ± 0.0 | 6.86 ± 0.47 | 0.5 ± 1.3 |

## Table C. SupplyGen operations (mean ± SD)

| Metric | Value |
|---|---|
| Council invocation rate (% of SKU-days) | 2.50 ± 2.54 |
| Triage precision (% invocations with a real disruption) | 98.7 ± 6.2 |
| Decision latency, mean (ms) | 7.35 ± 0.90 |
| Decision latency, p95 (ms) | 9.81 ± 2.91 |
| Council invocations per run | 90.1 ± 91.6 |
| Human escalations per run | 12.3 ± 10.9 |
| Supplier switches per run | 21.7 ± 15.4 |
| Orders clipped by guardrail per run | 0.00 ± 0.00 |

## Table D. Ablation and sensitivity (all scenarios pooled)

| Configuration | n | SBS | SBS reduction vs static % | Critical availability % | Invocation rate % | Total cost vs static % | Inventory vs static % |
|---|---|---|---|---|---|---|---|
| SupplyGen | 120 | 1318 ± 519 | 85.4 ± 7.2 | 99.8 ± 0.7 | 2.50 ± 2.54 | +6.0 | +19.9 |
| w/o Memory-Recall | 120 | 1578 ± 575 | 82.6 ± 8.9 | 98.9 ± 1.7 | 2.63 ± 2.81 | +5.8 | +15.7 |
| w/o Demand Forecaster | 120 | 2088 ± 1347 | 79.4 ± 9.1 | 98.8 ± 1.9 | 2.63 ± 2.80 | +5.4 | +14.4 |
| w/o Supplier Evaluator | 120 | 4227 ± 5087 | 62.2 ± 36.6 | 83.7 ± 26.4 | 2.02 ± 2.81 | +3.7 | +22.3 |
| w/o Triage (council on all SKU-days) | 20 | 0 ± 0 | 100.0 ± 0.0 | 100.0 ± 0.0 | 100.00 ± 0.00 | +11.5 | +79.2 |
| tau=0.1 | 40 | 926 ± 310 | 89.0 ± 6.2 | 99.8 ± 0.7 | 3.89 ± 2.09 | +6.6 | +41.7 |
| tau=0.3 | 40 | 1212 ± 545 | 86.3 ± 6.7 | 99.8 ± 0.5 | 3.06 ± 2.39 | +6.2 | +31.8 |
| tau=0.5 | 40 | 1325 ± 596 | 85.1 ± 7.2 | 99.8 ± 0.5 | 2.51 ± 2.48 | +5.9 | +20.2 |
| tau=0.6 | 40 | 1513 ± 1175 | 82.6 ± 15.4 | 99.0 ± 5.0 | 2.46 ± 2.58 | +5.8 | +18.3 |
| tau=0.7 | 40 | 3425 ± 3487 | 60.9 ± 38.6 | 91.6 ± 16.2 | 1.65 ± 2.32 | +4.2 | +12.9 |
| tau=0.8 | 40 | 6633 ± 4444 | 27.9 ± 41.0 | 75.1 ± 22.5 | 0.96 ± 2.15 | +2.0 | +7.1 |
| tau=0.9 | 40 | 9477 ± 3506 | 2.4 ± 14.9 | 63.1 ± 17.7 | 0.18 ± 1.14 | +0.3 | +1.1 |
| static z=2.0 | 120 | 9548 ± 3281 | 5.5 ± 3.8 | 62.6 ± 17.1 | - | +0.3 | +2.7 |
| static z=2.5 | 120 | 8889 ± 3214 | 12.5 ± 6.9 | 63.8 ± 17.4 | - | +0.8 | +6.7 |
| static z=3.0 | 120 | 8345 ± 3200 | 18.1 ± 10.0 | 65.0 ± 17.7 | - | +1.4 | +10.9 |
| static z=4.0 | 120 | 7571 ± 3196 | 25.9 ± 15.0 | 67.0 ± 19.0 | - | +2.5 | +19.2 |
| static z=6.0 | 120 | 6259 ± 3370 | 39.2 ± 20.2 | 70.7 ± 20.2 | - | +4.6 | +36.3 |
| static z=8.0 | 120 | 5175 ± 3647 | 50.6 ± 24.6 | 74.0 ± 20.7 | - | +6.1 | +54.1 |
