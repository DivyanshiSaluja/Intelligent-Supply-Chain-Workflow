"""Generate all result figures from results/ (run scripts/run_benchmark.py first).

    python scripts/make_figures.py
Writes figures/fig1..fig8 (PNG, 200 dpi).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from supplygen.config import FIGURES_DIR, RESULTS_DIR, SCENARIOS, SCENARIO_LABEL

# Plain matplotlib look: default colour cycle, boxed axes, white background.
C = {"Static ROP": "tab:blue", "Reactive dual-source": "tab:orange", "SupplyGen": "tab:green"}
INK = INK2 = "black"
MUTED, SURFACE = "gray", "white"
MAIN = ["Static ROP", "Reactive dual-source", "SupplyGen"]   # Adaptive ROP is reported in the tables
SHORT = [SCENARIO_LABEL[s].split(": ")[1] for s in SCENARIOS]

plt.rcdefaults()
plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.linestyle": "--", "grid.alpha": 0.5,
                     "axes.axisbelow": True, "savefig.dpi": 200, "savefig.bbox": "tight"})
BAR = {"edgecolor": "black", "linewidth": 0.6}
ERR = {"ecolor": "black", "elinewidth": 1, "capsize": 3}


def save(fig, name: str) -> None:
    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(FIGURES_DIR / name)
    plt.close(fig)
    print("wrote", FIGURES_DIR / name)


def grouped(ax, df, metric, fmt="{:.0f}"):
    w = 0.26
    for j, name in enumerate(MAIN):
        g = df[df.config == name].groupby("scenario")[metric]
        mean, sd = g.mean().reindex(SCENARIOS), g.std().reindex(SCENARIOS)
        x = np.arange(len(SCENARIOS)) + (j - 1) * w
        ax.bar(x, mean, w - 0.03, color=C[name], label=name, yerr=sd,
               error_kw=ERR, **BAR)
        for xi, m, s in zip(x, mean, sd):
            ax.text(xi, m + s, fmt.format(m), ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(np.arange(len(SCENARIOS)), SHORT)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)   # head-room for the legend
    ax.legend(ncol=3, loc="upper left", fontsize=9)


def main() -> None:
    runs = pd.read_csv(RESULTS_DIR / "runs.csv")
    main_df = runs[runs.group == "main"]
    n = main_df.seed.nunique()
    base = runs[runs.config == "Static ROP"].set_index(["scenario", "seed"])
    runs = runs.join(base[["sbs", "avg_inventory_units"]].rename(columns=lambda c: "base_" + c), on=["scenario", "seed"])
    runs["reduction"] = 100 * (runs.base_sbs - runs.sbs) / runs.base_sbs
    runs["inv_change"] = 100 * (runs.avg_inventory_units / runs.base_avg_inventory_units - 1)

    # Fig 1 - Stockout Burden Score by scenario
    fig, ax = plt.subplots(figsize=(8, 4.3))
    grouped(ax, main_df, "sbs")
    ax.set_ylabel("Stockout Burden Score (priority-weighted unmet units)")
    ax.set_title(f"Stockout Burden Score by stress scenario (mean ± SD, {n} runs each)")
    save(fig, "fig1_sbs_by_scenario.png")

    # Fig 2 - cumulative SBS over time
    cum = pd.read_csv(RESULTS_DIR / "cum_sbs.csv")
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.2), sharex=True, sharey=True)
    for ax, sc in zip(axes.flat, SCENARIOS):
        for name in MAIN:
            d = cum[(cum.config == name) & (cum.scenario == sc)]
            ax.plot(d.day, d["mean"], color=C[name], lw=1.6, label=name)
            ax.fill_between(d.day, d["mean"] - d.sd, d["mean"] + d.sd, color=C[name], alpha=0.2, lw=0)
            ax.text(d.day.iloc[-1] + 1.5, d["mean"].iloc[-1], f"{d['mean'].iloc[-1]:,.0f}", va="center",
                    fontsize=8, color=INK2)
        ax.set_title(SCENARIO_LABEL[sc], fontsize=10)
        ax.set_xlim(0, 134)
    for ax in axes[1]:
        ax.set_xlabel("Simulation day")
    for ax in axes[:, 0]:
        ax.set_ylabel("Cumulative SBS")
    axes[0, 0].legend(loc="upper left")
    fig.suptitle(f"Accumulation of stockout burden over the 120-day horizon (mean ± SD band, {n} runs)",
                 fontsize=12)
    fig.tight_layout()
    save(fig, "fig2_cumulative_sbs.png")

    # Fig 3 - critical-SKU availability
    fig, ax = plt.subplots(figsize=(8, 4.3))
    grouped(ax, main_df, "critical_availability", "{:.0f}%")
    ax.set_ylim(0, 128); ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Critical-SKU days in stock during disruption (%)")
    ax.set_title("Critical-SKU availability inside the disruption window (mean ± SD)")
    save(fig, "fig3_critical_availability.png")

    # Fig 4 - ablation
    order = ["SupplyGen", "w/o Memory-Recall", "w/o Demand Forecaster", "w/o Supplier Evaluator",
             "w/o Triage (council on all SKU-days)"]
    g = runs[runs.config.isin(order)].groupby("config")
    mean, sd, cnt = g.reduction.mean().reindex(order), g.reduction.std().reindex(order), g.size().reindex(order)
    inv = g.invocation_rate.mean().reindex(order)
    fig, ax = plt.subplots(figsize=(8.6, 3.8))
    y = np.arange(len(order))[::-1]
    ax.barh(y, mean, 0.6, color=[C["SupplyGen"]] + ["tab:blue"] * 4, xerr=sd,
            error_kw=ERR, **BAR)
    labels = ["SupplyGen (full)"] + order[1:]
    ax.set_yticks(y, [f"{l}\n(n={c})" for l, c in zip(labels, cnt)], fontsize=9)
    for yi, m, s, r in zip(y, mean, sd, inv):
        ax.text(min(m + s, 100) + 2, yi, f"{m:.1f}%   council on {r:.1f}% of SKU-days", va="center",
                fontsize=8.5, color=INK2)
    ax.set_xlim(0, 175); ax.set_xticks(range(0, 101, 20))
    
    ax.set_xlabel("SBS reduction vs Static ROP (%), all scenarios pooled, mean ± SD")
    ax.set_title("Ablation study: contribution of each component")
    save(fig, "fig4_ablation.png")

    # Fig 5 - sensitivity to the triage threshold
    t = runs[runs.group == "sens_tau"].copy()
    t["tau"] = t.config.str.replace("tau=", "").astype(float)
    g = t.groupby("tau")
    fig, axes = plt.subplots(2, 1, figsize=(7.5, 5.8), sharex=True)
    for ax, col, lab in ((axes[0], "reduction", "SBS reduction vs Static ROP (%)"),
                         (axes[1], "invocation_rate", "Council invocation rate (% of SKU-days)")):
        m, s = g[col].mean(), g[col].std()
        ax.plot(m.index, m, color=C["SupplyGen"], lw=1.6, marker="o", ms=6)
        ax.fill_between(m.index, (m - s).clip(lower=0), m + s, color=C["SupplyGen"], alpha=0.2, lw=0)
        for xi, v in m.items():
            ax.annotate(f"{v:.1f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center",
                        fontsize=8, color=INK2)
        ax.axvline(0.5, color=MUTED, lw=1, ls="--")
        ax.set_ylabel(lab, fontsize=9)
    axes[0].text(0.51, 5, "default 0.5", fontsize=8, color=MUTED)
    axes[1].set_xlabel("Triage threshold on signal risk (severity × credibility)")
    axes[0].set_title(f"Sensitivity to the triage threshold (mean ± SD band, {t.seed.nunique()} runs × 4 scenarios)")
    fig.tight_layout()
    save(fig, "fig5_sensitivity_triage.png")

    # Fig 6 - inventory vs service trade-off
    z = runs[runs.group == "sens_z"].copy()
    z["z"] = z.config.str.replace("static z=", "").astype(float)
    zm = z.groupby("z")[["inv_change", "sbs"]].mean()
    zm.loc[1.65] = [0.0, runs[runs.config == "Static ROP"].sbs.mean()]
    zm = zm.sort_index()
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.plot(zm.inv_change, zm.sbs, color=C["Static ROP"], lw=1.6, marker="o", ms=6,
            label="Static ROP with more safety stock (z = 1.65 to 8)")
    for zi, r in zm.iterrows():
        ax.annotate(f"z={zi:g}", (r.inv_change, r.sbs), textcoords="offset points", xytext=(5, 6),
                    fontsize=8, color=INK2)
    for name in ("Reactive dual-source", "SupplyGen"):
        d = runs[runs.config == name]
        ax.scatter(d.inv_change.mean(), d.sbs.mean(), s=90, color=C[name], label=name, zorder=3,
                   edgecolor="black", linewidth=0.8)
        ax.annotate(f"{name}\nSBS {d.sbs.mean():,.0f}", (d.inv_change.mean(), d.sbs.mean()),
                    textcoords="offset points", xytext=(10, -4), fontsize=8.5, color=INK2)
    ax.set_ylim(0, None)
    ax.set_xlabel("Average inventory held, change vs Static ROP (%)")
    ax.set_ylabel("Mean Stockout Burden Score")
    ax.set_title("Inventory-service trade-off: buffers alone vs signal-aware decisions")
    ax.legend(loc="upper right")
    save(fig, "fig6_inventory_service_tradeoff.png")

    # Fig 7 - council workload
    sg = main_df[main_df.config == "SupplyGen"].groupby("scenario")
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    for ax, col, title, fmt in ((axes[0], "invocation_rate", "Council invocation rate (% of SKU-days)", "{:.2f}%"),
                                (axes[1], "hitl_escalations", "Human approvals requested per run", "{:.1f}"),
                                (axes[2], "latency_ms_mean", "Mean decision latency (ms)", "{:.1f}")):
        m, s = sg[col].mean().reindex(SCENARIOS), sg[col].std().reindex(SCENARIOS)
        ax.bar(range(4), m, 0.6, color=C["SupplyGen"], yerr=[np.minimum(s, m), s], error_kw=ERR, **BAR)
        for i, (v, e) in enumerate(zip(m, s)):
            ax.text(i, v + e, fmt.format(v), ha="center", va="bottom", fontsize=8, color=INK2)
        ax.set_xticks(range(4), [x.replace(" ", "\n") for x in SHORT], fontsize=8)
        ax.set_title(title, fontsize=9.5)
    fig.suptitle("SupplyGen council workload by scenario (mean ± SD)", fontsize=12)
    fig.tight_layout()
    save(fig, "fig7_council_workload.png")

    # Fig 8 - stock trace of one critical SKU
    tr = json.loads((RESULTS_DIR / "trace.json").read_text())
    fig, ax = plt.subplots(figsize=(8.5, 4))
    ax.axvspan(tr["start"], tr["end"], color="gray", alpha=0.15, lw=0)
    ax.text((tr["start"] + tr["end"]) / 2, 0.97, "supplier failure window", transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=8.5, color=INK2)
    ax.axvline(tr["published"], color=MUTED, lw=1, ls="--")
    ax.text(tr["published"] + 0.8, 0.86, "signal\npublished", transform=ax.get_xaxis_transform(), fontsize=8, color=MUTED)
    for name in ("Static ROP", "SupplyGen"):
        ax.plot(tr[name], color=C[name], lw=1.6, label=name)
    ax.set_xlabel("Simulation day"); ax.set_ylabel("On-hand stock (units)")
    ax.set_title(f"Stock trace of a critical SKU under supplier failure: {tr['sku']} (seed 0)")
    ax.legend()
    save(fig, "fig8_stock_trace.png")


if __name__ == "__main__":
    main()
