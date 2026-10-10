"""Draw the system architecture and the decision flowchart, and export the LangGraph.

    python scripts/make_diagrams.py
Writes figures/system_architecture.png, figures/workflow_flowchart.png and
figures/council_graph.mmd (Mermaid source generated from the compiled LangGraph).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon

from supplygen.config import FIGURES_DIR, Policy
from supplygen.graph import build_graph

INK, INK2, LINE, SURFACE = "black", "black", "black", "white"
FILL = {"data": "lightblue", "triage": "moccasin", "council": "lightgreen", "gov": "lightsalmon", "plain": "lightgray"}
plt.rcParams.update({"savefig.dpi": 200, "savefig.bbox": "tight",
                     "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE})


def box(ax, x, y, w, h, text, kind="plain", size=7.3, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="square,pad=0", fc=FILL[kind],
                                ec=LINE, lw=1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK,
            fontweight="bold" if bold else "normal")
    return (x + w / 2, y + h / 2, w, h)


def diamond(ax, cx, cy, w, h, text):
    ax.add_patch(Polygon([(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
                         fc=FILL["triage"], ec=LINE, lw=1))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=7.3, color=INK)


def arrow(ax, p, q, label=None, dx=0.0, dy=0.0):
    ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1.1, shrinkA=0, shrinkB=0))
    if label:
        ax.text((p[0] + q[0]) / 2 + dx, (p[1] + q[1]) / 2 + dy, label, fontsize=7.5, color=INK2, ha="center", va="center")


def layer(ax, y, h, title, tx=2.5):
    ax.add_patch(FancyBboxPatch((1, y), 98, h, boxstyle="square,pad=0", fc="none", ec=LINE,
                                lw=1, ls=(0, (4, 3))))
    ax.text(tx, y + h - 2.2, title, fontsize=9, fontweight="bold", color=INK2, va="center")


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(11, 9.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

    layer(ax, 77, 22, "Layer 1  Data and signal ingestion")
    for i, t in enumerate(["News\n(GDELT)", "Weather\n(Open-Meteo)", "Festival calendar\n(Nager.Date / local)", "Commodity prices\n(FRED)"]):
        box(ax, 4 + i * 14.5, 86, 13, 7, t, "data")
        arrow(ax, (10.5 + i * 14.5, 86), (10.5 + i * 14.5, 84))
    box(ax, 4, 78.5, 56.5, 5.5, "Signal normaliser  ->  disruption_events (type, target, window, severity, credibility)", "data")
    box(ax, 66, 78.5, 30, 14.5, "SQLite warehouse\nskus, suppliers, sku_suppliers\ndemand_history (12 months)\ninventory_state (daily stock)\nmemory_episodes", "data")

    layer(ax, 58, 16.5, "Layer 2  Signal triage (runs for every SKU-day)")
    box(ax, 4, 60.5, 44, 8.5, "Signal-triage classifier\nrisk = severity x credibility >= threshold\nand stock position < risk-adjusted need", "triage")
    box(ax, 62, 60.5, 34, 8.5, "Fast path\nstatic reorder-point rule\n(about 97.5% of SKU-days)", "plain")
    arrow(ax, (20, 78.5), (20, 69)); arrow(ax, (70, 78.5), (44, 69))
    arrow(ax, (48, 64.7), (62, 64.7), "not at risk", dy=1.6)

    layer(ax, 30, 25.5, "Layer 3  Council of Agents (LangGraph state graph, structured JSON between nodes)", tx=24)
    names = ["Signal\nAnalyst", "Memory-\nRecall", "Demand\nForecaster", "Supplier\nEvaluator", "Replenishment\nPlanner"]
    for i, t in enumerate(names):
        box(ax, 4 + i * 19, 39, 15.5, 8.5, t, "council", bold=True)
        if i:
            arrow(ax, (4 + i * 19 - 3.5, 43.2), (4 + i * 19, 43.2))
    arrow(ax, (11.7, 60.5), (11.7, 47.5))
    ax.text(13, 51.5, "at-risk\nSKU-day", fontsize=7.5, color=INK2, va="center")
    for i, t in enumerate(["which signals are\ncredible and whom\nthey hit", "what past\ndisruptions of this\ntype actually did",
                           "daily forecast with\nfestival uplift", "effective lead time,\nfill and cost per\nsupplier",
                           "action, quantity,\nsupplier"]):
        ax.text(11.7 + i * 19, 35, t, ha="center", va="center", fontsize=7.5, color=INK2)

    layer(ax, 2, 25.5, "Layer 4  Governance and execution")
    box(ax, 4, 10, 20, 9, "Supervisor\nguardrails: approved supplier,\ncost premium, quantity cap", "gov", bold=False)
    box(ax, 29, 10, 18, 9, "Human approval\n(LangGraph interrupt)\nlarge value, critical switch,\ncost premium", "gov")
    box(ax, 52, 10, 18, 9, "Audit logger\nrationale_text for\nevery decision", "gov")
    box(ax, 75, 10, 21, 9, "decisions_log +\npurchase order (ERP adapter)", "data")
    arrow(ax, (87.7, 39), (87.7, 22), None); arrow(ax, (87.7, 22), (14, 22)); arrow(ax, (14, 22), (14, 19))
    arrow(ax, (24, 14.5), (29, 14.5), "escalate", dy=1.6); arrow(ax, (47, 14.5), (52, 14.5)); arrow(ax, (70, 14.5), (75, 14.5))
    arrow(ax, (14, 10), (14, 6)); arrow(ax, (14, 6), (61, 6), "auto-approved", dy=1.4); arrow(ax, (61, 6), (61, 10))
    ax.text(50, 3.4, "LangSmith traces every council invocation and hosts the decision-level evaluation",
            ha="center", fontsize=8.5, color=INK2, style="italic")
    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(FIGURES_DIR / "system_architecture.png"); plt.close(fig)
    print("wrote", FIGURES_DIR / "system_architecture.png")


def flowchart() -> None:
    fig, ax = plt.subplots(figsize=(8.5, 11.5))
    ax.set_xlim(0, 100); ax.set_ylim(0, 120); ax.axis("off")
    cx = 38
    box(ax, cx - 17, 112, 34, 6, "START: daily tick for one SKU", "plain", bold=True)
    box(ax, cx - 19, 102, 38, 6, "Read stock position and published signals", "data")
    diamond(ax, cx, 91, 44, 11, "Credible signal for this SKU?\n(risk >= threshold)")
    diamond(ax, cx, 76, 44, 11, "Position below\nrisk-adjusted need?")
    box(ax, cx - 23, 61.5, 46, 6.5, "Council of Agents\nAnalyst > Memory > Forecast > Suppliers > Plan", "council", bold=False)
    box(ax, cx - 23, 51, 46, 6.5, "Supervisor guardrails\n(clip quantity, block unapproved or costly supplier)", "gov")
    diamond(ax, cx, 39, 44, 11, "Needs human approval?\n(value, critical switch, premium)")
    diamond(ax, cx, 24, 36, 10, "Human approves?")
    box(ax, cx - 19, 9, 38, 6.5, "Write purchase order and\ndecision record with rationale", "data")
    box(ax, cx - 12, 0, 24, 5, "END", "plain", bold=True)
    box(ax, 70, 80.5, 28, 9, "Fast path:\nposition <= reorder point?\norder from primary : no action", "plain")
    box(ax, 66, 20.5, 22, 7, "Hold: no order,\nrejection logged", "plain")

    arrow(ax, (cx, 112), (cx, 108)); arrow(ax, (cx, 102), (cx, 96.5))
    arrow(ax, (cx, 85.5), (cx, 81.5), "yes", dx=3); arrow(ax, (cx, 70.5), (cx, 68), "yes", dx=3)
    arrow(ax, (cx, 61.5), (cx, 57.5)); arrow(ax, (cx, 51), (cx, 44.5))
    arrow(ax, (cx, 33.5), (cx, 29), "yes", dx=3); arrow(ax, (cx, 19), (cx, 15.5), "yes", dx=3)
    arrow(ax, (cx, 9), (cx, 5))
    ax.plot([cx + 22, 84], [91, 91], color=INK2, lw=1.1); ax.text(64, 92.6, "no", fontsize=7.5, color=INK2)
    arrow(ax, (84, 91), (84, 89.5))
    arrow(ax, (cx + 22, 76), (70, 82.5), "no", dy=-2)
    arrow(ax, (cx + 18, 24), (66, 24), "no", dy=1.6)
    # "no approval needed" bypass on the left
    ax.plot([cx - 22, 8, 8], [39, 39, 12.2], color=INK2, lw=1.1); arrow(ax, (8, 12.2), (cx - 19, 12.2))
    ax.text(9.5, 41, "no", fontsize=7.5, color=INK2)
    # fast path and hold join the end
    ax.plot([94, 94, cx + 12], [80.5, 2.5, 2.5], color=INK2, lw=1.1)
    ax.plot([77, 77], [20.5, 2.5], color=INK2, lw=1.1); arrow(ax, (cx + 13, 2.5), (cx + 12, 2.5))
    fig.savefig(FIGURES_DIR / "workflow_flowchart.png"); plt.close(fig)
    print("wrote", FIGURES_DIR / "workflow_flowchart.png")


def tech_stack() -> None:
    fig, ax = plt.subplots(figsize=(6.5, 7.5))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")
    rows = [("Evaluation and tracing", "LangSmith (traces, dataset, experiments) | pytest", "gov"),
            ("Language model (optional planner, briefings)", "qwen3:8b served locally by Ollama (REST API)", "triage"),
            ("Agent orchestration", "LangGraph state graph: 8 nodes, conditional edge, interrupt", "council"),
            ("Core language and numerics", "Python 3.14 | NumPy | pandas | Matplotlib", "data"),
            ("Simulation and data", "Seeded inventory simulator | SQLite warehouse", "plain"),
            ("External signals and real data", "Open-Meteo | GDELT | Nager.Date | FRED | UCI Online Retail II", "data")]
    for i, (label, text, kind) in enumerate(rows):
        y = 85 - i * 16
        box(ax, 8, y, 84, 8, text, kind, size=8)
        ax.text(50, y - 3, label, ha="center", va="center", fontsize=9, fontweight="bold", color=INK)
        if i:
            arrow(ax, (50, y + 8), (50, y + 11))
    fig.savefig(FIGURES_DIR / "technology_stack.png"); plt.close(fig)
    print("wrote", FIGURES_DIR / "technology_stack.png")


if __name__ == "__main__":
    architecture()
    flowchart()
    tech_stack()
    mmd = build_graph(Policy(), []).get_graph().draw_mermaid()
    (FIGURES_DIR / "council_graph.mmd").write_text(mmd, encoding="utf-8")
    print("wrote", FIGURES_DIR / "council_graph.mmd")
