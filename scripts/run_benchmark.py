"""Run the full benchmark: comparison, ablation and sensitivity studies.

    python scripts/run_benchmark.py              # 30 runs per scenario (about 10-20 min)
    python scripts/run_benchmark.py --runs 5     # quick check
    python scripts/run_benchmark.py --dataset real   # replay real demand (UCI Online Retail II)
Outputs go to results/ or results/real/ (runs.csv, cum_sbs.csv, trace.json, summary.json, summary.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LANGSMITH_TRACING"] = "false"   # tracing 100k+ runs is not useful
REAL = "real" in sys.argv[1:]
if REAL:   # must be set before supplygen is imported; worker processes inherit it
    os.environ["SUPPLYGEN_DB"] = str(Path(__file__).resolve().parent.parent / "data" / "real_demand.db")

import numpy as np

from supplygen.config import RESULTS_DIR, SCENARIOS, SCENARIO_LABEL, Policy
from supplygen.controllers import AdaptiveROP, ReactiveDual, StaticROP, SupplyGen
from supplygen.db import load_master
from supplygen.simulation import Simulation

TAUS = [0.1, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9]
ZS = [2.0, 2.5, 3.0, 4.0, 6.0, 8.0]
P = Policy()

# name -> (group, factory)
CONFIGS = {
    "Static ROP": ("main", lambda: StaticROP(P)),
    "Adaptive ROP": ("main", lambda: AdaptiveROP(P)),
    "Reactive dual-source": ("main", lambda: ReactiveDual(P)),
    "SupplyGen": ("main", lambda: SupplyGen(P)),
    "w/o Memory-Recall": ("ablation", lambda: SupplyGen(P.but(use_memory=False), "w/o Memory-Recall")),
    "w/o Demand Forecaster": ("ablation", lambda: SupplyGen(P.but(use_forecaster=False), "w/o Demand Forecaster")),
    "w/o Supplier Evaluator": ("ablation", lambda: SupplyGen(P.but(use_supplier_eval=False), "w/o Supplier Evaluator")),
    "w/o Triage (council on all SKU-days)": ("ablation_slow", lambda: SupplyGen(P.but(use_triage=False), "w/o Triage (council on all SKU-days)")),
    **{f"tau={t}": ("sens_tau", (lambda t=t: SupplyGen(P.but(triage_threshold=t), f"tau={t}"))) for t in TAUS},
    **{f"static z={z}": ("sens_z", (lambda z=z: _static_z(z))) for z in ZS},
}
_MASTER = None
MAIN = ["Static ROP", "Adaptive ROP", "Reactive dual-source", "SupplyGen"]
OUT = RESULTS_DIR / "real" if REAL else RESULTS_DIR


def _static_z(z: float) -> StaticROP:
    c = StaticROP(P.but(z=z))
    c.name = f"static z={z}"
    return c


def run_one(task: tuple[str, str, int]) -> dict:
    global _MASTER
    name, scenario, seed = task
    if _MASTER is None:
        _MASTER = load_master()
    res = Simulation(_MASTER, scenario, seed).run(CONFIGS[name][1]())
    row = {"config": name, "group": CONFIGS[name][0], "scenario": scenario, "seed": seed, **res.metrics}
    extra = {"cum": res.cum_sbs.tolist()} if CONFIGS[name][0] == "main" else {}
    return {"row": row, **extra}


def trace(master) -> dict:
    """Stock trace of one critical SKU hit by the supplier failure (seed 0), for Figure 8."""
    sim = Simulation(master, "supplier_failure", 0)
    i = next(int(k) for k in sim.affected_skus() if master.skus[k]["priority_tier"] == "critical")
    sig = sim.truth[0]
    out = {"sku": f"{master.skus[i]['sku_code']} {master.skus[i]['name']}",
           "start": sig["start_day"], "end": sig["end_day"], "published": sig["published_day"]}
    for c in (StaticROP(P), SupplyGen(P)):
        out[c.name] = sim.run(c).on_hand[:, i].tolist()
    return out


def ms(v) -> tuple[float, float]:
    v = np.asarray(v, dtype=float)
    return float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0


def summarise(rows: list[dict]) -> dict:
    by = {}
    for r in rows:
        by.setdefault(r["config"], {})[(r["scenario"], r["seed"])] = r
    base, reactive = by["Static ROP"], by["Reactive dual-source"]
    rng = np.random.default_rng(0)
    out = {"n_runs_main": len({k[1] for k in base}), "configs": {}}
    for name, runs in by.items():
        keys = sorted(runs)
        red = np.array([100 * (base[k]["sbs"] - runs[k]["sbs"]) / base[k]["sbs"] for k in keys if base[k]["sbs"] > 0])
        boot = [red[rng.integers(len(red), size=len(red))].mean() for _ in range(2000)]
        vs_r = [100 * (reactive[k]["sbs"] - runs[k]["sbs"]) / reactive[k]["sbs"] for k in keys if reactive[k]["sbs"] > 0]
        entry = {"n": len(keys), "vs_reactive_mean": ms(vs_r)[0], "vs_reactive_sd": ms(vs_r)[1],
                 "wins_vs_reactive": int(sum(v > 0 for v in vs_r)),
                 "sbs_reduction_mean": ms(red)[0], "sbs_reduction_sd": ms(red)[1],
                 "sbs_reduction_ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                 "wins_vs_static": int((red > 0).sum()), "pairs": len(red),
                 "cost_change_pct": ms([100 * (runs[k]["total_cost"] / base[k]["total_cost"] - 1) for k in keys])[0],
                 "unit_cost_change_pct": ms([100 * (runs[k]["cost_per_unit_sold"] / base[k]["cost_per_unit_sold"] - 1) for k in keys])[0],
                 "inventory_change_pct": ms([100 * (runs[k]["avg_inventory_units"] / base[k]["avg_inventory_units"] - 1) for k in keys])[0]}
        metrics = [m for m in runs[keys[0]] if m not in ("config", "group", "scenario", "seed")]
        for m in metrics:
            entry[m] = dict(zip(("mean", "sd"), ms([runs[k][m] for k in keys])))
        entry["by_scenario"] = {}
        for sc in SCENARIOS:
            ks = [k for k in keys if k[0] == sc]
            if not ks:
                continue
            r2 = [100 * (base[k]["sbs"] - runs[k]["sbs"]) / base[k]["sbs"] for k in ks if base[k]["sbs"] > 0]
            entry["by_scenario"][sc] = {"sbs_reduction": dict(zip(("mean", "sd"), ms(r2))),
                                        **{m: dict(zip(("mean", "sd"), ms([runs[k][m] for k in ks]))) for m in metrics}}
        out["configs"][name] = entry
    return out


def markdown(s: dict) -> str:
    c = s["configs"]
    f = lambda e, m, d=1: f"{e[m]['mean']:.{d}f} ± {e[m]['sd']:.{d}f}"
    L = [f"# SupplyGen benchmark summary{' - REAL DEMAND (UCI Online Retail II)' if REAL else ''} ({s['n_runs_main']} runs x {len(SCENARIOS)} scenarios)\n",
         "## Table A. Overall comparison (mean ± SD over all scenario-runs)\n",
         "| Controller | SBS | Burden % | Fill rate % | Critical availability % | Critical protection % | SBS reduction vs static % | Total cost vs static % | Cost per unit sold vs static % | Inventory vs static % |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for n in MAIN:
        e = c[n]
        L.append(f"| {n} | {f(e, 'sbs', 0)} | {f(e, 'burden_pct', 2)} | {f(e, 'fill_rate', 2)} | "
                 f"{f(e, 'critical_availability')} | {f(e, 'critical_protection')} | "
                 f"{e['sbs_reduction_mean']:.1f} ± {e['sbs_reduction_sd']:.1f} | {e['cost_change_pct']:+.1f} | {e['unit_cost_change_pct']:+.1f} | {e['inventory_change_pct']:+.1f} |")
    e = c["SupplyGen"]
    L += ["", f"SupplyGen SBS reduction 95% bootstrap CI: [{e['sbs_reduction_ci95'][0]:.1f}, {e['sbs_reduction_ci95'][1]:.1f}]; "
              f"lower SBS than static in {e['wins_vs_static']}/{e['pairs']} paired scenario-runs. "
              f"Against the reactive dual-source baseline: {e['vs_reactive_mean']:.1f} ± {e['vs_reactive_sd']:.1f}% lower SBS, "
              f"better in {e['wins_vs_reactive']}/{e['pairs']}.", "",
          "## Table B. Per scenario\n",
          "| Scenario | Static SBS | Adaptive SBS | Reactive SBS | SupplyGen SBS | Reduction % | Crit. avail. static % | Crit. avail. SupplyGen % | Invocation rate % | HITL escalations / run |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for sc in SCENARIOS:
        b, a, r, g = (c[n]["by_scenario"][sc] for n in MAIN)
        L.append(f"| {SCENARIO_LABEL[sc]} | {f(b, 'sbs', 0)} | {f(a, 'sbs', 0)} | {f(r, 'sbs', 0)} | {f(g, 'sbs', 0)} | {f(g, 'sbs_reduction')} | "
                 f"{f(b, 'critical_availability')} | {f(g, 'critical_availability')} | {f(g, 'invocation_rate', 2)} | {f(g, 'hitl_escalations')} |")
    L += ["", "## Table C. SupplyGen operations (mean ± SD)\n", "| Metric | Value |", "|---|---|"]
    for m, lab, d in (("invocation_rate", "Council invocation rate (% of SKU-days)", 2),
                      ("triage_precision", "Triage precision (% invocations with a real disruption)", 1),
                      ("latency_ms_mean", "Decision latency, mean (ms)", 2), ("latency_ms_p95", "Decision latency, p95 (ms)", 2),
                      ("council_invocations", "Council invocations per run", 1), ("hitl_escalations", "Human escalations per run", 1),
                      ("supplier_switches", "Supplier switches per run", 1), ("clipped_orders", "Orders clipped by guardrail per run", 2)):
        L.append(f"| {lab} | {f(e, m, d)} |")
    L += ["", "## Table D. Ablation and sensitivity (all scenarios pooled)\n",
          "| Configuration | n | SBS | SBS reduction vs static % | Critical availability % | Invocation rate % | Total cost vs static % | Inventory vs static % |", "|---|---|---|---|---|---|---|---|"]
    for n, e in c.items():
        if n in MAIN[:3]:
            continue
        inv = f(e, "invocation_rate", 2) if "invocation_rate" in e else "-"
        L.append(f"| {n} | {e['n']} | {f(e, 'sbs', 0)} | {e['sbs_reduction_mean']:.1f} ± {e['sbs_reduction_sd']:.1f} | "
                 f"{f(e, 'critical_availability')} | {inv} | {e['cost_change_pct']:+.1f} | {e['inventory_change_pct']:+.1f} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30, help="independent seeds per scenario")
    ap.add_argument("--dataset", choices=["synthetic", "real"], default="synthetic")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    n_for = {"main": a.runs, "ablation": a.runs, "sens_z": a.runs,
             "sens_tau": min(a.runs, 10), "ablation_slow": min(a.runs, 5)}
    tasks = [(name, sc, seed) for name, (grp, _) in CONFIGS.items()
             for sc in SCENARIOS for seed in range(n_for[grp])]
    print(f"{len(tasks)} simulation runs on {a.workers} workers ...")
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        results = list(ex.map(run_one, tasks, chunksize=4))
    print(f"done in {time.time() - t0:.0f}s")

    OUT.mkdir(parents=True, exist_ok=True)
    rows = [r["row"] for r in results]
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader(); w.writerows(rows)
    with open(OUT / "cum_sbs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["config", "scenario", "day", "mean", "sd"])
        for name in MAIN:
            for sc in SCENARIOS:
                cum = np.array([r["cum"] for r in results if r["row"]["config"] == name and r["row"]["scenario"] == sc])
                for d in range(cum.shape[1]):
                    w.writerow([name, sc, d, round(cum[:, d].mean(), 2), round(cum[:, d].std(ddof=1) if len(cum) > 1 else 0, 2)])
    (OUT / "trace.json").write_text(json.dumps(trace(load_master())), encoding="utf-8")
    s = summarise(rows)
    (OUT / "summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (OUT / "summary.md").write_text(markdown(s), encoding="utf-8")
    print(markdown(s))


if __name__ == "__main__":
    main()
