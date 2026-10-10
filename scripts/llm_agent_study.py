"""LLM-in-the-loop study: the local LLM replaces the rule-based Replenishment Planner.

For every reorder moment the council is run with the LLM planner (qwen3 via Ollama).
The LLM's supplier and quantity are compared with the rule-based planner on the same
facts, then scored by the same evaluators used for the static baseline.

    python scripts/llm_agent_study.py --seeds 3        # 54 moments
With LANGSMITH_TRACING=true each case is a trace tagged 'llm-planner'.
Writes results/llm_agent_study.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import langsmith_eval as ev
from supplygen.config import RESULTS_DIR
from supplygen.graph import build_graph
from supplygen.llm import MODEL


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    examples = ev.build_examples(a.seeds)
    graph = build_graph(ev.POLICY, ev.MASTER.episodes, llm_planner=True)
    rows = []
    for n, ex in enumerate(examples, 1):
        t0 = time.perf_counter()
        out = graph.invoke({"ctx": ex["inputs"]["ctx"], "signals": ex["inputs"]["signals"], "hitl_mode": "auto"},
                           {"run_name": f"llm planner case {n}", "tags": ["llm-planner", ex["outputs"]["scenario"]]})
        p, d, ref = out["proposal"], out["decision"], ex["outputs"]
        raw = {"action": p["action"], "qty": p["qty"], "chosen_supplier_id": p["chosen_supplier_id"]}
        row = {"case": n, "scenario": ref["scenario"], "should_protect": ref["should_protect"],
               "source": p["source"], "seconds": round(time.perf_counter() - t0, 2),
               "llm_qty": p["qty"], "rule_qty": p.get("rule_qty", p["qty"]),
               "llm_supplier": p["chosen_supplier_id"], "rule_supplier": p.get("rule_supplier_id", p["chosen_supplier_id"]),
               "same_action": p["action"] == p.get("rule_action", p["action"]),
               "same_supplier": p["chosen_supplier_id"] == p.get("rule_supplier_id", p["chosen_supplier_id"]),
               "supervisor_status": d["supervisor_status"],
               "raw_avoids_disrupted": ev.avoids_disrupted_supplier(raw, ref),
               "raw_protective": ev.protective_action(ex["inputs"], raw, ref),
               "raw_within_cap": ev.within_guardrails(raw, ref),
               "final_avoids_disrupted": ev.avoids_disrupted_supplier(d, ref),
               "final_protective": ev.protective_action(ex["inputs"], d, ref),
               "final_within_cap": ev.within_guardrails(d, ref),
               "reason": p.get("llm_reason", "")}
        rows.append(row)
        print(f"{n:3d}/{len(examples)} {row['scenario']:20s} {row['source']:13s} llm {row['llm_qty']:5d} "
              f"(sup {row['llm_supplier']}) rule {row['rule_qty']:5d} (sup {row['rule_supplier']}) {row['seconds']:6.1f}s",
              flush=True)

    llm = [r for r in rows if r["source"] == "llm"]
    pct = lambda key, src=rows: round(100 * sum(r[key] for r in src) / max(len(src), 1), 1)
    ratio = np.array([r["llm_qty"] / r["rule_qty"] for r in llm if r["rule_qty"] > 0])
    summary = {
        "model": MODEL, "cases": len(rows), "valid_llm_output_pct": round(100 * len(llm) / len(rows), 1),
        "same_supplier_as_rule_pct": pct("same_supplier", llm), "same_action_as_rule_pct": pct("same_action", llm),
        "qty_ratio_llm_over_rule_median": round(float(np.median(ratio)), 2) if len(ratio) else None,
        "qty_within_25pct_of_rule_pct": round(100 * float((np.abs(ratio - 1) <= 0.25).mean()), 1) if len(ratio) else None,
        "raw_llm": {k: pct("raw_" + k) for k in ("avoids_disrupted", "protective", "within_cap")},
        "after_supervisor": {k: pct("final_" + k) for k in ("avoids_disrupted", "protective", "within_cap")},
        "orders_changed_by_supervisor_pct": round(100 * sum(r["supervisor_status"] != "approved" for r in rows) / len(rows), 1),
        "seconds_per_decision_mean": round(float(np.mean([r["seconds"] for r in rows])), 1),
        "seconds_per_decision_p95": round(float(np.percentile([r["seconds"] for r in rows], 95)), 1)}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "llm_agent_study.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
