# SupplyGen benchmark summary - REAL DEMAND (UCI Online Retail II) (30 runs x 4 scenarios)

## Table A. Overall comparison (mean ± SD over all scenario-runs)

| Controller | SBS | Burden % | Fill rate % | Critical availability % | Critical protection % | SBS reduction vs static % | Total cost vs static % | Cost per unit sold vs static % | Inventory vs static % |
|---|---|---|---|---|---|---|---|---|---|
| Static ROP | 22858 ± 10234 | 5.99 ± 2.28 | 93.91 ± 2.22 | 86.4 ± 11.1 | 38.4 ± 27.3 | 0.0 ± 0.0 | +0.0 | +0.0 | +0.0 |
| Adaptive ROP | 18044 ± 6509 | 4.90 ± 1.88 | 95.19 ± 1.80 | 86.8 ± 9.8 | 25.1 ± 25.5 | 10.4 ± 36.4 | +1.4 | +0.0 | +23.7 |
| Reactive dual-source | 17615 ± 10045 | 4.51 ± 2.13 | 95.36 ± 2.19 | 94.1 ± 5.5 | 53.6 ± 22.3 | 22.9 ± 24.2 | +1.7 | +0.1 | +3.5 |
| SupplyGen | 11138 ± 7167 | 2.89 ± 1.59 | 97.03 ± 1.63 | 99.5 ± 1.6 | 91.7 ± 16.1 | 50.1 ± 18.4 | +5.3 | +1.9 | +16.3 |

SupplyGen SBS reduction 95% bootstrap CI: [46.9, 53.4]; lower SBS than static in 120/120 paired scenario-runs. Against the reactive dual-source baseline: 32.1 ± 22.5% lower SBS, better in 113/120.

## Table B. Per scenario

| Scenario | Static SBS | Adaptive SBS | Reactive SBS | SupplyGen SBS | Reduction % | Crit. avail. static % | Crit. avail. SupplyGen % | Invocation rate % | HITL escalations / run |
|---|---|---|---|---|---|---|---|---|---|
| A: Commodity shortage | 17564 ± 9767 | 14353 ± 3843 | 12603 ± 7711 | 9726 ± 7402 | 46.4 ± 14.1 | 86.8 ± 9.1 | 99.7 ± 0.7 | 1.16 ± 0.22 | 18.2 ± 5.1 |
| B: Supplier failure | 27745 ± 10251 | 26309 ± 6406 | 12848 ± 8209 | 10080 ± 8089 | 66.5 ± 13.4 | 74.0 ± 8.6 | 98.8 ± 2.9 | 1.27 ± 0.13 | 7.4 ± 2.3 |
| C: Weather disruption | 16815 ± 9162 | 14295 ± 3473 | 15702 ± 9035 | 12638 ± 8949 | 28.8 ± 12.1 | 87.7 ± 7.8 | 99.7 ± 0.9 | 0.75 ± 0.15 | 3.9 ± 1.2 |
| D: Festival surge | 29308 ± 3287 | 17218 ± 2445 | 29308 ± 3287 | 12107 ± 1987 | 58.7 ± 5.3 | 97.3 ± 0.7 | 99.8 ± 0.2 | 13.56 ± 1.17 | 0.1 ± 0.6 |

## Table C. SupplyGen operations (mean ± SD)

| Metric | Value |
|---|---|
| Council invocation rate (% of SKU-days) | 4.18 ± 5.47 |
| Triage precision (% invocations with a real disruption) | 98.7 ± 6.5 |
| Decision latency, mean (ms) | 7.12 ± 0.37 |
| Decision latency, p95 (ms) | 8.93 ± 0.59 |
| Council invocations per run | 150.6 ± 197.0 |
| Human escalations per run | 7.4 ± 7.3 |
| Supplier switches per run | 14.2 ± 9.4 |
| Orders clipped by guardrail per run | 0.07 ± 0.41 |

## Table D. Ablation and sensitivity (all scenarios pooled)

| Configuration | n | SBS | SBS reduction vs static % | Critical availability % | Invocation rate % | Total cost vs static % | Inventory vs static % |
|---|---|---|---|---|---|---|---|
| SupplyGen | 120 | 11138 ± 7167 | 50.1 ± 18.4 | 99.5 ± 1.6 | 4.18 ± 5.47 | +5.3 | +16.3 |
| w/o Memory-Recall | 120 | 11786 ± 7230 | 46.9 ± 19.4 | 99.0 ± 2.2 | 4.28 ± 5.68 | +5.4 | +17.0 |
| w/o Demand Forecaster | 120 | 13309 ± 8377 | 42.6 ± 19.8 | 99.4 ± 1.4 | 4.46 ± 6.08 | +4.9 | +10.8 |
| w/o Supplier Evaluator | 120 | 15748 ± 10155 | 31.7 ± 23.7 | 92.3 ± 11.7 | 3.67 ± 5.75 | +3.6 | +18.5 |
| w/o Triage (council on all SKU-days) | 20 | 2844 ± 2633 | 90.1 ± 9.2 | 100.0 ± 0.0 | 100.00 ± 0.00 | +18.0 | +51.9 |
| tau=0.1 | 40 | 9528 ± 7360 | 60.6 ± 14.5 | 99.5 ± 1.9 | 5.39 ± 4.81 | +7.6 | +28.0 |
| tau=0.3 | 40 | 10888 ± 8414 | 54.3 ± 18.6 | 99.4 ± 2.4 | 4.72 ± 5.36 | +6.4 | +22.5 |
| tau=0.5 | 40 | 11703 ± 8562 | 50.3 ± 19.4 | 99.3 ± 2.2 | 4.24 ± 5.56 | +5.6 | +17.7 |
| tau=0.6 | 40 | 11853 ± 8555 | 49.3 ± 20.5 | 99.1 ± 2.4 | 4.22 ± 5.65 | +5.5 | +15.7 |
| tau=0.7 | 40 | 14680 ± 9946 | 36.0 ± 27.7 | 97.4 ± 5.4 | 2.77 ± 4.99 | +3.9 | +10.7 |
| tau=0.8 | 40 | 19383 ± 11085 | 15.4 ± 24.4 | 90.9 ± 10.7 | 1.68 ± 4.33 | +2.0 | +6.1 |
| tau=0.9 | 40 | 23441 ± 11567 | 1.3 ± 8.0 | 86.6 ± 11.3 | 0.36 ± 2.28 | +0.3 | +1.1 |
| static z=2.0 | 120 | 18021 ± 8486 | 22.2 ± 8.5 | 88.4 ± 10.2 | - | +2.6 | +8.5 |
| static z=2.5 | 120 | 13993 ± 7885 | 42.4 ± 14.0 | 90.0 ± 9.4 | - | +5.6 | +21.0 |
| static z=3.0 | 120 | 10655 ± 6612 | 57.3 ± 14.7 | 91.3 ± 8.6 | - | +8.5 | +33.9 |
| static z=4.0 | 120 | 6597 ± 5032 | 74.4 ± 12.3 | 93.6 ± 7.6 | - | +13.4 | +60.6 |
| static z=6.0 | 120 | 2748 ± 3028 | 90.1 ± 8.2 | 97.0 ± 5.2 | - | +22.4 | +112.0 |
| static z=8.0 | 120 | 850 ± 1708 | 97.0 ± 4.9 | 98.6 ± 3.5 | - | +30.9 | +163.5 |
