"""Figures for the two validation studies.

    python scripts/make_figures_extra.py
fig9  decision-level evaluation: static rule vs rule-based council vs LLM planner
fig10 real-demand replay (UCI Online Retail II): SBS and critical availability
Needs results/llm_agent_study.json and results/real/runs.csv.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LANGSMITH_TRACING"] = "false"

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import langsmith_eval as ev
import make_figures as mf
from supplygen.config import RESULTS_DIR

LLM_COLOR = "tab:purple"


def fig9() -> None:
    study = json.loads((RESULTS_DIR / "llm_agent_study.json").read_text())
    s, n = study["summary"], study["summary"]["cases"]
    seeds = max(1, round(n / 18))
    local = ev.run_local(ev.build_examples(seeds))
    keys = [("avoids_disrupted_supplier", "avoids_disrupted", "Avoids the\ndisrupted supplier"),
            ("protective_action", "protective", "Protective action\nwhen affected"),
            ("within_guardrails", "within_cap", "Within quantity\nguardrail")]
    series = [("Static ROP rule", mf.C["Static ROP"], [local["Static ROP"][k] for k, _, _ in keys]),
              ("Council, rule-based planner", mf.C["SupplyGen"], [local["SupplyGen"][k] for k, _, _ in keys]),
              (f"Council, LLM planner ({s['model']})", LLM_COLOR, [s["after_supervisor"][k] for _, k, _ in keys])]
    fig, ax = plt.subplots(figsize=(8.6, 4.3))
    w = 0.26
    for j, (name, color, vals) in enumerate(series):
        x = np.arange(3) + (j - 1) * w
        ax.bar(x, vals, w - 0.03, color=color, label=name, **mf.BAR)
        for xi, v in zip(x, vals):
            ax.text(xi, v + 1.5, f"{v:.0f}%", ha="center", fontsize=8, color=mf.INK2)
    ax.set_xticks(np.arange(3), [k[2] for k in keys])
    ax.set_ylim(0, 128); ax.set_yticks(range(0, 101, 20)); ax.set_ylabel("Reorder moments passed (%)")
    ax.set_title(f"Decision-level evaluation on {n} reorder moments during live disruptions")
    ax.legend(ncol=3, loc="upper left", fontsize=8)
    mf.save(fig, "fig9_decision_eval_llm.png")


def fig10() -> None:
    runs = pd.read_csv(RESULTS_DIR / "real" / "runs.csv")
    df = runs[runs.group == "main"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    mf.grouped(axes[0], df, "sbs")
    axes[0].set_ylabel("Stockout Burden Score"); axes[0].set_title("Stockout Burden Score", fontsize=10)
    mf.grouped(axes[1], df, "critical_availability", "{:.0f}%")
    axes[1].set_ylim(0, 128); axes[1].set_yticks(range(0, 101, 20))
    axes[1].set_ylabel("Critical-SKU days in stock (%)"); axes[1].set_title("Critical-SKU availability during disruption", fontsize=10)
    axes[0].get_legend().remove()
    fig.suptitle(f"Real-demand replay, UCI Online Retail II (mean ± SD, {df.seed.nunique()} demand windows per scenario)",
                 fontsize=12)
    fig.tight_layout()
    mf.save(fig, "fig10_real_demand.png")


def fig11_12() -> None:
    """Overall SBS and critical-SKU protection rate, pooled over scenarios, both datasets."""
    data = {"Synthetic demand": pd.read_csv(RESULTS_DIR / "runs.csv"),
            "Real demand (UCI Online Retail II)": pd.read_csv(RESULTS_DIR / "real" / "runs.csv")}
    for name, metric, ylabel, title, fmt in (
            ("fig11_overall_sbs.png", "sbs", "Stockout Burden Score", "Total Stockout Burden Score, all scenarios pooled (mean ± SD, 120 runs)", "{:,.0f}"),
            ("fig12_critical_protection.png", "critical_protection", "Affected critical SKUs with no stockout (%)",
             "Critical-SKU protection success rate, all scenarios pooled (mean ± SD, 120 runs)", "{:.1f}%")):
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
        for ax, (label, runs) in zip(axes, data.items()):
            g = runs[runs.config.isin(mf.MAIN)].groupby("config")[metric]
            m, s = g.mean().reindex(mf.MAIN), g.std().reindex(mf.MAIN)
            ax.bar(range(3), m, 0.6, color=[mf.C[c] for c in mf.MAIN], yerr=[np.minimum(s, m), s], error_kw=mf.ERR, **mf.BAR)
            for i, (v, e) in enumerate(zip(m, s)):
                ax.text(i, v + e, fmt.format(v), ha="center", va="bottom", fontsize=9)
            ax.set_xticks(range(3), [c.replace(" dual-source", "\ndual-source") for c in mf.MAIN])
            ax.set_ylabel(ylabel); ax.set_title(label, fontsize=10)
            ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
        fig.suptitle(title, fontsize=12)
        fig.tight_layout()
        mf.save(fig, name)


def fig13() -> None:
    """What the Supplier Evaluator saw in one supplier-failure decision."""
    snap = json.loads((RESULTS_DIR / "snapshot.json").read_text())
    rank = snap["ranking"]
    names = [r["name"].replace(" ", "\n", 1) + ("\n(chosen)" if r["supplier_id"] == snap["chosen"] else "") for r in rank]
    colors = ["tab:green" if r["supplier_id"] == snap["chosen"] else "tab:red" if r["affected_by"] else "tab:blue" for r in rank]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.9))
    for ax, key, title, fmt in ((axes[0], "eff_lead", "Effective lead time (days)", "{:.0f}"),
                                (axes[1], "premium", "Cost premium vs primary (%)", "{:+.0f}%"),
                                (axes[2], "score", "Evaluator score (lower is better)", "{:.1f}")):
        vals = [r[key] * (100 if key == "premium" else 1) for r in rank]
        ax.bar(range(len(rank)), vals, 0.6, color=colors, **mf.BAR)
        for i, v in enumerate(vals):
            ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=9)
        ax.set_xticks(range(len(rank)), names, fontsize=8); ax.set_title(title, fontsize=10)
        ax.set_ylim(min(0, min(vals) * 1.3), max(vals) * 1.15 + 0.5)
    fig.suptitle(f"Supplier snapshot for {snap['sku']} on day {snap['day']} of the supplier-failure run "
                 "(red: supplier hit by the disruption)", fontsize=11)
    fig.tight_layout()
    mf.save(fig, "fig13_supplier_snapshot.png")


if __name__ == "__main__":
    for f in (fig10, fig9, fig11_12, fig13):
        try:
            f()
        except FileNotFoundError as exc:
            print(f"skipped {f.__name__}: {exc.filename} not found")
